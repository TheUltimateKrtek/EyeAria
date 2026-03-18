import sys
import time
import uuid
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import subprocess
import os
import webbrowser
import threading
from typing import Optional
from nicegui import ui, app
from Node import Node, NodeRegistry
from Schema import PipelinePayload
import logging

logger = logging.getLogger(__name__)

@NodeRegistry.register("Postgres Sink")
class PostgresSink(Node):
    has_input = True
    has_output = False 
    node_color = "sky-700" 

    def __init__(self):
        super().__init__()
        # 1. Connection Config (Network or Local)
        self.host = "127.0.0.1" # Can be changed to a network IP
        self.port = 5432
        self.dbname = "eyearia"
        self.user = "postgres"
        self.password = "postgres"
        
        # 2. Local DB Server Config (Only used for Local Manager)
        self.data_dir = "./postgres_data"
        
        # Runtime internals
        self.conn: Optional[psycopg2.extensions.connection] = None
        self.session_id = None
        self.session_inserted = False
        self.msg_count = 0
        self.last_status = "Stopped"
        self.server_running = False
        
        # Streamlit process tracker
        self.dashboard_process = None
        app.on_shutdown(self._cleanup_dashboard)

    def _start(self):
        self.last_status = "Connecting..."
        self._update_status_ui()
        
        try:
            self.conn = psycopg2.connect(
                host=self.host, port=self.port, dbname=self.dbname, 
                user=self.user, password=self.password
            )
            self.session_id = str(uuid.uuid4())
            self.session_inserted = False 
            self.msg_count = 0
            
            self.last_status = "Connected & Recording"
            self._update_status_ui()
        except Exception as e:
            self.last_status = f"Connection Error"
            self._update_status_ui()
            logger.error(f"Failed to connect to postgres: {e}")
            self.running = False

    def _stop(self):
        if self.conn:
            self.conn.close()
            self.conn = None
        self.last_status = "Stopped"
        self._update_status_ui()
        
    def _input(self, payload: PipelinePayload):
        if not self.running or not self.conn: 
            return None
        
        try:
            cur = self.conn.cursor()
            
            # 1. Insert the Session Metadata
            if not self.session_inserted:
                cur.execute("""
                    INSERT INTO sessions (session_id, model_name, pi_uuid, camera_url, start_time)
                    VALUES (%s, %s, %s, %s, to_timestamp(%s))
                """, (
                    self.session_id, payload.model_name, payload.pi_uuid, 
                    payload.camera_url, payload.timestamp
                ))
                self.session_inserted = True

            # 2. Insert Detections
            for det in payload.detections:
                cur.execute("""
                    INSERT INTO detections (
                        session_id, timestamp, label, confidence, 
                        bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax, track_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    self.session_id, payload.timestamp,
                    det.label, det.confidence,
                    det.bbox[0], det.bbox[1], det.bbox[2], det.bbox[3], 
                    det.track_id
                ))
            
            self.conn.commit()
            cur.close()
            
            self.msg_count += len(payload.detections)
            if hasattr(self, 'msg_counter_label'):
                self.msg_counter_label.set_text(f"Rows inserted: {self.msg_count}")
                
        except Exception as e:
            logger.error(f"DB Insert failed: {e}")
        return None

    # --- GENERAL DATABASE ACTIONS ---
    
    def test_connection(self):
        try:
            test_conn = psycopg2.connect(
                host=self.host, port=self.port, dbname=self.dbname, 
                user=self.user, password=self.password
            )
            test_conn.close()
            ui.notify(f"Successfully connected to {self.dbname} at {self.host}!", color='positive')
        except Exception as e:
            ui.notify(f"Connection failed: {e}", color='negative')

    def build_tables(self):
        """Creates the tables in whatever database is currently configured."""
        try:
            conn = psycopg2.connect(
                host=self.host, port=self.port, dbname=self.dbname, 
                user=self.user, password=self.password
            )
            cur = conn.cursor()
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id VARCHAR(36) PRIMARY KEY,
                    model_name VARCHAR(255),
                    pi_uuid VARCHAR(255),
                    camera_url VARCHAR(255),
                    start_time TIMESTAMP
                );
            """)
            
            # Updated xmin/xmax to bbox_xmin/bbox_xmax
            cur.execute("""
                CREATE TABLE IF NOT EXISTS detections (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(36) REFERENCES sessions(session_id),
                    timestamp DOUBLE PRECISION,
                    label VARCHAR(255),
                    confidence DOUBLE PRECISION,
                    bbox_xmin DOUBLE PRECISION,
                    bbox_ymin DOUBLE PRECISION,
                    bbox_xmax DOUBLE PRECISION,
                    bbox_ymax DOUBLE PRECISION,
                    track_id INTEGER
                );
            """)
            
            conn.commit()
            cur.close()
            conn.close()
            ui.notify("Schema tables created successfully!", color='positive')
        except Exception as e:
            ui.notify(f"Table Creation Error: {e}", color='negative')

    # --- DASHBOARD MANAGEMENT ---

    def _cleanup_dashboard(self):
        """Ensures the Streamlit server is killed when EyeAria exits."""
        if self.dashboard_process and self.dashboard_process.poll() is None:
            self.dashboard_process.terminate()
            self.dashboard_process = None

    def toggle_dashboard(self):
        """Starts or stops the Streamlit dashboard as a background process."""
        if self.dashboard_process is None or self.dashboard_process.poll() is not None:
            # --- START DASHBOARD ---
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                dashboard_path = os.path.join(script_dir, "streamlit_dashboard.py")
                
                if not os.path.exists(dashboard_path):
                    ui.notify("Could not find streamlit_dashboard.py in the current directory.", color="negative")
                    return

                # 1. Inject the Postgres node's configuration into the environment
                custom_env = os.environ.copy()
                custom_env["DB_HOST"] = self.host
                custom_env["DB_PORT"] = str(self.port)
                custom_env["DB_NAME"] = self.dbname
                custom_env["DB_USER"] = self.user
                custom_env["DB_PASS"] = self.password

                # 2. Launch Streamlit, forcing it to listen on all network interfaces
                self.dashboard_process = subprocess.Popen(
                    [
                        sys.executable, "-m", "streamlit", "run", dashboard_path, 
                        "--server.headless", "true",
                        "--server.address", "0.0.0.0"  # NEW: Allow remote access
                    ],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env=custom_env
                )
                
                ui.notify("Dashboard starting...", color="positive")
                self.dashboard_btn.set_text("Stop Dashboard")
                self.dashboard_btn.props('color=red icon=stop')

                # 3. Dynamically grab the server's hostname/IP from the browser and open the tab
                js_redirect = """
                    const serverHost = window.location.hostname;
                    const serverProtocol = window.location.protocol;
                    window.open(serverProtocol + "//" + serverHost + ":8501", "_blank");
                """
                ui.timer(2.0, lambda: ui.run_javascript(js_redirect), once=True)

            except Exception as e:
                ui.notify(f"Failed to start dashboard: {e}", color="negative")
                logger.error(f"Streamlit launch error: {e}")
        else:
            # --- STOP DASHBOARD ---
            self.dashboard_process.terminate()
            self.dashboard_process = None
            
            self.dashboard_btn.set_text("Launch Dashboard")
            self.dashboard_btn.props('color=sky icon=dashboard')
            ui.notify("Dashboard stopped.", color="info")

    # --- LOCAL SERVER MANAGEMENT COMMANDS ---

    def execute_initdb(self):
        target_dir = os.path.abspath(self.data_dir)
        # 1. Define the absolute path to the initdb binary
        initdb_bin = "/usr/lib/postgresql/15/bin/initdb"
        
        try:
            os.makedirs(target_dir, exist_ok=True)
            # 2. Use the absolute path in the subprocess call
            result = subprocess.run([initdb_bin, "-D", target_dir, "-U", self.user, "-A", "trust"], capture_output=True, text=True)
            
            if result.returncode == 0:
                ui.notify(f"Database cluster initialized at {target_dir}", color="positive")
            else:
                ui.notify(f"initdb failed: {result.stderr}", color="negative")
        except FileNotFoundError:
            ui.notify(f"Error: '{initdb_bin}' command not found. Is PostgreSQL 15 installed locally?", color="negative")
        except Exception as e:
            ui.notify(f"Error initializing: {e}", color="negative")

    def check_local_server_status(self):
        """Checks if the Postgres cluster is currently running and updates the UI."""
        target_dir = os.path.abspath(self.data_dir)
        pg_ctl_bin = "/usr/lib/postgresql/15/bin/pg_ctl"
        
        custom_env = os.environ.copy()
        custom_env["PATH"] += os.pathsep + "/usr/lib/postgresql/15/bin"
        
        try:
            # pg_ctl status returns 0 if running, or 3/4 if stopped/no directory
            result = subprocess.run([pg_ctl_bin, "-D", target_dir, "status"], capture_output=True, text=True, env=custom_env)
            self.server_running = (result.returncode == 0)
        except Exception:
            self.server_running = False
            
        # Update the button text and color if the dialog is open
        if hasattr(self, 'toggle_btn'):
            if self.server_running:
                self.toggle_btn.set_text("Stop Local Server")
                self.toggle_btn.props('color=red icon=stop')
            else:
                self.toggle_btn.set_text("Start Local Server")
                self.toggle_btn.props('color=green icon=play_arrow')

    def toggle_server(self):
        """Starts or stops the server based on its current known status."""
        target_dir = os.path.abspath(self.data_dir)
        log_file = os.path.join(target_dir, "server.log")
        pg_ctl_bin = "/usr/lib/postgresql/15/bin/pg_ctl"
        
        custom_env = os.environ.copy()
        custom_env["PATH"] += os.pathsep + "/usr/lib/postgresql/15/bin"
        
        action = "stop" if self.server_running else "start"
        
        try:
            if action == "start":
                cmd = [pg_ctl_bin, "-D", target_dir, "-l", log_file, "-o", f"-p {self.port} -k /tmp", "start"]
            else:
                cmd = [pg_ctl_bin, "-D", target_dir, "stop"]
                
            result = subprocess.run(cmd, capture_output=True, text=True, env=custom_env)
            
            if result.returncode == 0:
                ui.notify(f"Local Server {action}ed successfully.", color="positive")
            else:
                # --- EXTRACT THE REAL ERROR ---
                detailed_error = result.stderr.strip()
                if os.path.exists(log_file):
                    with open(log_file, "r") as f:
                        logs = f.read().strip()
                        if logs:
                            # Get the last 3 lines of the log
                            detailed_error = "\n".join(logs.splitlines()[-3:])
                
                if not detailed_error:
                    detailed_error = "Unknown Error. (Are you running this script as root/sudo?)"

                ui.notify(f"DB Error:\n{detailed_error}", color="negative", multi_line=True)
                print(f"--- POSTGRES STARTUP ERROR ---\n{detailed_error}\n------------------------------")
                
        except FileNotFoundError:
            ui.notify(f"Error: '{pg_ctl_bin}' command not found.", color="negative")
            
        self.check_local_server_status()

    def create_local_database(self):
        """Creates the logical database. Used only if the DB doesn't exist yet."""
        try:
            # Connect to default 'postgres' db to create the new one
            conn_setup = psycopg2.connect(
                host=self.host, port=self.port, dbname='postgres', 
                user=self.user, password=self.password
            )
            conn_setup.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cur = conn_setup.cursor()
            
            cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (self.dbname,))
            if not cur.fetchone():
                safe_db_name = "".join(c for c in self.dbname if c.isalnum() or c == '_')
                cur.execute(f"CREATE DATABASE {safe_db_name}")
                ui.notify(f"Database '{self.dbname}' created!", color='positive')
            else:
                ui.notify(f"Database '{self.dbname}' already exists.", color='info')
            
            cur.close()
            conn_setup.close()
        except Exception as e:
            ui.notify(f"Create Database Error: {e}", color='negative')

    def open_management_dialog(self):
        """Dialog to handle OS-level Postgres actions."""
        with ui.dialog() as dialog, ui.card().classes('w-[450px] p-4 gap-4'):
            with ui.row().classes('w-full items-center justify-between border-b pb-2'):
                ui.label("Local DB Server Manager").classes('text-lg font-bold text-sky-800')
                ui.button(icon="close", on_click=dialog.close).props('flat round size=sm')
            
            ui.label("Use this to set up a database on this specific machine. Ensure PostgreSQL binaries are installed.").classes('text-xs text-slate-500 mb-2')
            
            with ui.column().classes('w-full border border-sky-100 p-3 rounded gap-2 bg-sky-50/50'):
                ui.label("1. Initialize Cluster").classes('font-bold text-xs text-sky-900')
                ui.input("Data Directory Path", value=self.data_dir).bind_value(self, 'data_dir').classes('w-full text-xs').props('dense')
                ui.button("Run initdb", on_click=self.execute_initdb).props('outline size=sm color=sky').classes('w-full')

            with ui.column().classes('w-full border border-sky-100 p-3 rounded gap-2 bg-sky-50/50'):
                ui.label("2. Start / Stop Server").classes('font-bold text-xs text-sky-900')
                
                # Replace the row of two buttons with this single smart button
                self.toggle_btn = ui.button("Checking Status...", on_click=self.toggle_server).classes('w-full').props('size=sm')
                # Check status immediately to set the correct color/text
                self.check_local_server_status()
                    
            with ui.column().classes('w-full border border-sky-100 p-3 rounded gap-2 bg-sky-50/50'):
                ui.label("3. Create Database").classes('font-bold text-xs text-sky-900')
                ui.label(f"Creates a DB named '{self.dbname}'").classes('text-[10px] text-slate-500')
                ui.button("Create DB", on_click=self.create_local_database).props('outline size=sm color=sky').classes('w-full')
            
            with ui.column().classes('w-full border border-sky-100 p-3 rounded gap-2 bg-sky-50/50'):
                ui.label("4. Table Setup").classes('font-bold text-xs text-sky-900')
                ui.label(f"Generates the tables.").classes('text-[10px] text-slate-500')
                ui.button("Build Tables", on_click=self.build_tables).props('outline size=sm color=sky').classes('w-full')

        dialog.open()

    def _update_status_ui(self):
        if hasattr(self, 'status_label'):
            self.status_label.set_text(str(self.last_status))
            color = "text-green-600" if self.conn else "text-red-500"
            self.status_label.classes(replace=f"text-[10px] font-mono {color}")

    def create_content(self):
        with ui.column().classes('w-full gap-2'):
            # 1. Connection Config
            with ui.column().classes('bg-slate-50 border border-slate-200 border-l-4 border-l-sky-500 w-full p-2 shadow-sm gap-1'):
                ui.label("TARGET DATABASE").classes('text-[10px] font-bold text-slate-700')
                
                with ui.row().classes('w-full items-center gap-2'):
                    ui.input(label="Host / IP").bind_value(self, 'host').classes('text-xs grow').props('dense')
                    ui.number(label="Port", format="%d").bind_value(self, 'port').classes('w-1/3 text-xs').props('dense')
                
                ui.input(label="DB Name").bind_value(self, 'dbname').classes('w-full text-xs').props('dense')
                
                with ui.row().classes('w-full items-center gap-2'):
                    ui.input(label="User").bind_value(self, 'user').classes('w-1/2 text-xs').props('dense')
                    ui.input(label="Password", password=True).bind_value(self, 'password').classes('w-1/2 text-xs').props('dense')
                
                with ui.row().classes('w-full gap-1 mt-1'):
                    ui.button("Test Connection", on_click=self.test_connection).props('outline size=sm color=slate').classes('w-full')

            # 2. Local Manager
            ui.button("Local Server Setup...", on_click=self.open_management_dialog)\
                .props('flat size=sm color=sky icon=dns').classes('w-full bg-slate-100 border border-slate-200')
            
            # NEW: Dashboard Launcher
            self.dashboard_btn = ui.button(
                "Launch Dashboard", 
                on_click=self.toggle_dashboard
            ).props('outline size=sm color=sky icon=dashboard').classes('w-full')

            # 3. Status Output
            with ui.column().classes('bg-white border border-slate-200 border-l-4 border-l-slate-400 w-full p-2 shadow-sm gap-1'):
                with ui.row().classes('w-full items-center justify-between'):
                    self.status_label = ui.label("Status: Idle").classes("text-[10px] font-mono")
                    self.msg_counter_label = ui.label(f"Rows inserted: {self.msg_count}").classes("text-[10px] font-mono")

    def save(self) -> dict:
        data = super().save()
        data.update({
            "host": self.host, "port": self.port, "dbname": self.dbname,
            "user": self.user, "password": self.password, "data_dir": self.data_dir
        })
        return data

    def _load_config(self, data: dict):
        self.host = data.get("host", "127.0.0.1")
        self.port = int(data.get("port", 5432))
        self.dbname = data.get("dbname", "eyearia")
        self.user = data.get("user", "postgres")
        self.password = data.get("password", "postgres")
        self.data_dir = data.get("data_dir", "./postgres_data")