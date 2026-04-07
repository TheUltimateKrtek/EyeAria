import threading
import queue
import time
import random
from nicegui import ui
from Node import Node, NodeRegistry
from Schema import ModuleData, PipelinePayload
from typing import Optional

@NodeRegistry.register("MPU-9250 IMU")
class IMUNode(Node):
    node_color = "teal-700"
    has_input = False  # It is a hardware source
    has_output = True

    def __init__(self):
        super().__init__()
        # 1. Hardware Config
        self.i2c_bus = 1
        self.i2c_address = "0x68"
        self.polling_rate_hz = 50
        
        # 2. Runtime Internals
        self.sensor_thread = None
        self.data_queue = queue.Queue()
        self.poll_timer = None
        
        # 3. UI State variables for live display
        self.latest_accel = [0.0, 0.0, 0.0]
        self.latest_gyro = [0.0, 0.0, 0.0]

    def _start(self):
        # 1. Hardware Initialization would go here
        # Example: self.sensor = mpu9250.MPU9250(bus=self.i2c_bus, address=int(self.i2c_address, 16))
        
        if hasattr(self, 'status_label'):
            self.status_label.set_text("Status: Reading I2C...")

        # 2. Launch the high-speed background polling thread
        self.sensor_thread = threading.Thread(target=self._hardware_loop, daemon=True)
        self.sensor_thread.start()
        
        # 3. Launch the UI synchronizer timer
        # We poll the UI queue slightly slower than the hardware to batch updates and save CPU
        self.poll_timer = ui.timer(0.05, self.check_queue)

    def _hardware_loop(self):
        """Runs in the background, talking to the I2C bus as fast as configured."""
        delay = 1.0 / max(1, self.polling_rate_hz)
        
        while self.running:
            start_time = time.time()
            
            # --- REPLACE THIS WITH YOUR REAL I2C READS ---
            # accel = self.sensor.read_accel_data()
            # gyro = self.sensor.read_gyro_data()
            accel = [random.uniform(-1.0, 1.0) for _ in range(3)] 
            gyro = [random.uniform(-5.0, 5.0) for _ in range(3)]
            temp = 25.0 + random.uniform(-0.5, 0.5)
            # ---------------------------------------------

            # 1. Package the specific sensor data
            sensor_data = {
                "config": {"bus": self.i2c_bus, "address": self.i2c_address, "hz": self.polling_rate_hz},
                "accel": accel,
                "gyro": gyro,
                "temp": temp
            }
            
            # 2. Wrap it in the standard ModuleData contract
            module_key = f"{self._node_type_name.replace(' ', '_')}_{self.id[:6]}"
            module_chunk = ModuleData(
                name=module_key,
                is_new=True,
                data=sensor_data
            )
            
            # 3. Safely push to the queue
            self.data_queue.put({module_key: module_chunk})
            
            # 4. Sleep to enforce the configured Hz rate
            elapsed = time.time() - start_time
            sleep_time = max(0, delay - elapsed)
            time.sleep(sleep_time)

    def check_queue(self):
        """Runs on the UI thread, pops data, updates UI, and pushes to Gateway."""
        try:
            # We use a while loop to instantly flush any backlog that built up in the queue
            while not self.data_queue.empty():
                chunk = self.data_queue.get_nowait()
                
                module_key = list(chunk.keys())[0]
                mod_data = chunk[module_key]
                
                # Update UI state variables
                self.latest_accel = mod_data.data.get('accel', [0,0,0])
                self.latest_gyro = mod_data.data.get('gyro', [0,0,0])
                
                # Push to the Gateway
                self.notify(chunk)
                
            # Update the nicegui labels once per UI tick to avoid freezing the browser
            if hasattr(self, 'accel_label'):
                self.accel_label.set_text(f"Accel: x={self.latest_accel[0]:.2f}, y={self.latest_accel[1]:.2f}, z={self.latest_accel[2]:.2f}")
                self.gyro_label.set_text(f"Gyro:  x={self.latest_gyro[0]:.2f}, y={self.latest_gyro[1]:.2f}, z={self.latest_gyro[2]:.2f}")
                
        except queue.Empty:
            pass
    
    def _input(self, payload: PipelinePayload) -> Optional[PipelinePayload]:
        # Source nodes don't process incoming payloads, 
        # but we must implement the abstract method.
        return None

    def _stop(self):
        if self.poll_timer: 
            self.poll_timer.cancel()
            
        if self.sensor_thread and self.sensor_thread.is_alive():
            self.sensor_thread.join(timeout=1.0)
            
        if hasattr(self, 'status_label'):
            self.status_label.set_text("Status: Idle")
            self.accel_label.set_text("Accel: ---")
            self.gyro_label.set_text("Gyro:  ---")

    def create_content(self):
        with ui.column().classes('bg-teal-50 border border-slate-200 border-l-4 border-l-teal-600 w-full p-2 mb-2 shadow-sm gap-1'):
            ui.label("I2C CONFIGURATION").classes('text-[10px] font-bold text-teal-800')
            
            with ui.row().classes('w-full items-center gap-2'):
                ui.number(label="I2C Bus", format="%d").bind_value(self, 'i2c_bus').classes('w-16 text-xs').props('dense')
                ui.input(label="Address (Hex)").bind_value(self, 'i2c_address').classes('grow text-xs').props('dense')
                
            ui.number(label="Polling Rate (Hz)", format="%d").bind_value(self, 'polling_rate_hz').classes('w-full text-xs').props('dense')

        with ui.column().classes('bg-slate-900 border border-slate-800 w-full p-2 mb-2 shadow-inner gap-1 rounded'):
            ui.label("LIVE TELEMETRY").classes('text-[9px] font-bold text-slate-400 tracking-wider')
            self.accel_label = ui.label("Accel: ---").classes('text-[11px] text-green-400 font-mono leading-tight')
            self.gyro_label = ui.label("Gyro:  ---").classes('text-[11px] text-blue-400 font-mono leading-tight')

        with ui.row().classes('w-full items-center justify-between px-2'):
            self.status_label = ui.label("Status: Idle").classes("text-[10px] text-slate-500 font-mono")

    def save(self) -> dict:
        data = super().save()
        data.update({
            "i2c_bus": self.i2c_bus,
            "i2c_address": self.i2c_address,
            "polling_rate_hz": self.polling_rate_hz
        })
        return data

    def _load_config(self, data: dict):
        self.i2c_bus = data.get("i2c_bus", 1)
        self.i2c_address = data.get("i2c_address", "0x68")
        self.polling_rate_hz = data.get("polling_rate_hz", 50)