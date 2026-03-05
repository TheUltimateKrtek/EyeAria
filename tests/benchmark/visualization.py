import streamlit as st
import pandas as pd
import altair as alt
import os
import json
import cv2

st.set_page_config(page_title="Hailo Pipeline Benchmarks", layout="wide")
st.title("Hailo Object Detection Pipeline Benchmarks")

DATA_FILE = "benchmark_results.csv"
JSON_FILE = "benchmark_detections.json"
VIDEO_FILE = "temp_benchmark_video.mp4"

if not os.path.exists(DATA_FILE):
    st.error(f"Data file '{DATA_FILE}' not found. Please run the benchmark script first.")
else:
    df = pd.read_csv(DATA_FILE)
    
    # Create the unified Config label
    df["Config"] = df.apply(
        lambda row: f"{'Track' if row['Tracking Enabled'] else 'NoTrack'} | {'Frames' if row['Frame Materialization'] else 'NoFrames'}", 
        axis=1
    )

    tab1, tab2, tab3 = st.tabs(["Performance (FPS)", "Detection Analytics", "Frame Visualizer"])

    # ==========================================
    # TAB 1: FPS PERFORMANCE
    # ==========================================
    with tab1:
        st.markdown("### FPS Comparison (Grouped by Model)")
        model_order = ['yolov8n', 'yolov8s', 'yolov8m', 'yolov8l', 'yolov8x']
        
        fps_chart = alt.Chart(df).mark_bar().encode(
            x=alt.X('Config:N', title=None, axis=alt.Axis(labels=False, ticks=False)),
            y=alt.Y('FPS:Q', title='Frames Per Second'),
            color=alt.Color('Config:N', legend=alt.Legend(title="Pipeline Config", orient="bottom")),
            column=alt.Column('Model:N', sort=model_order, header=alt.Header(title="Model Size", labelOrient='bottom')),
            tooltip=['Model', 'Config', 'FPS', 'Avg Detections']
        ).properties(width=150, height=450)
        
        st.altair_chart(fps_chart, theme="streamlit", use_container_width=False)
        st.dataframe(df, use_container_width=True)

    # ==========================================
    # TAB 2: DETECTION ANALYTICS (JSON DATA)
    # ==========================================
    with tab2:
        if not os.path.exists(JSON_FILE):
            st.warning("Detection data JSON not found.")
        else:
            with open(JSON_FILE, 'r') as f:
                det_data = json.load(f)

            # Build DataFrames for Analytics
            records = []
            frame_records = []
            baseline_config = "Track-False_Frames-False"

            for run_id, frames in det_data.items():
                model = run_id.split('_')[0]
                config = run_id.split('_', 1)[1]
                
                for f_data in frames:
                    # Frame-level data (for Line Charts) - only using baseline config to avoid duplicates
                    if config == baseline_config:
                        confs = [d['confidence'] for d in f_data['detections']]
                        avg_conf = sum(confs) / len(confs) if confs else 0.0
                        frame_records.append({
                            'Model': model,
                            'Frame': f_data['frame_count'],
                            'NumDetections': f_data['num_detections'],
                            'AvgConfidence': avg_conf
                        })

                    # Object-level data (for Bar/Box Charts)
                    for d in f_data['detections']:
                        records.append({
                            'Model': model,
                            'Config': config,
                            'Frame': f_data['frame_count'],
                            'Label': d['label'],
                            'Confidence': d['confidence']
                        })
            
            det_df = pd.DataFrame(records)
            frames_df = pd.DataFrame(frame_records)

            if det_df.empty:
                st.info("No objects were detected.")
            else:
                baseline_df = det_df[det_df['Config'] == baseline_config]

                st.markdown("### Frame-by-Frame Timeline")
                st.markdown("Tracking the stability of detections and confidence scores throughout the video.")
                
                colA, colB = st.columns(2)
                
                with colA:
                    st.subheader("Detections over Time")
                    line_det = alt.Chart(frames_df).mark_line().encode(
                        x=alt.X('Frame:Q', title="Frame Number"),
                        y=alt.Y('NumDetections:Q', title="Number of Objects Detected"),
                        color=alt.Color('Model:N', sort=model_order),
                        tooltip=['Model', 'Frame', 'NumDetections']
                    ).properties(height=300)
                    st.altair_chart(line_det, use_container_width=True)
                    
                with colB:
                    st.subheader("Average Confidence over Time")
                    line_conf = alt.Chart(frames_df).mark_line().encode(
                        x=alt.X('Frame:Q', title="Frame Number"),
                        y=alt.Y('AvgConfidence:Q', title="Average Confidence Score", scale=alt.Scale(domain=[0, 1])),
                        color=alt.Color('Model:N', sort=model_order),
                        tooltip=['Model', 'Frame', 'AvgConfidence']
                    ).properties(height=300)
                    st.altair_chart(line_conf, use_container_width=True)

                st.divider()

                st.markdown("### Overall Object Accuracy (Baseline Config)")
                col1, col2 = st.columns(2)

                with col1:
                    st.subheader("Average Confidence Score")
                    conf_chart = alt.Chart(baseline_df).mark_bar().encode(
                        x=alt.X('Model:N', sort=model_order, axis=alt.Axis(labelAngle=0)),
                        y=alt.Y('mean(Confidence):Q', title='Average Confidence', scale=alt.Scale(domain=[0, 1])),
                        color=alt.Color('Model:N', legend=None),
                        tooltip=['Model', 'mean(Confidence)', 'count(Confidence)']
                    ).properties(height=300)
                    st.altair_chart(conf_chart, use_container_width=True)

                with col2:
                    st.subheader("Total Objects Detected (By Class)")
                    count_chart = alt.Chart(baseline_df).mark_bar().encode(
                        x=alt.X('Model:N', sort=model_order, axis=alt.Axis(labelAngle=0)),
                        y=alt.Y('count():Q', title='Total Bounding Boxes Detected'),
                        color=alt.Color('Label:N', legend=alt.Legend(title="Object Class")),
                        tooltip=['Model', 'Label', 'count()']
                    ).properties(height=300)
                    st.altair_chart(count_chart, use_container_width=True)

    # ==========================================
    # TAB 3: FRAME VISUALIZER
    # ==========================================
    with tab3:
        st.markdown("### Visual Verification")
        st.markdown("Select a frame and a model to see exactly what the AI detected. (Using baseline configuration: `NoTrack | NoFrames`)")

        if not os.path.exists(VIDEO_FILE):
            st.error(f"Video file '{VIDEO_FILE}' not found. Ensure the benchmark script didn't delete it.")
        elif not os.path.exists(JSON_FILE):
            st.error("JSON detection data not found.")
        else:
            with open(JSON_FILE, 'r') as f:
                det_data = json.load(f)
            
            available_models = sorted(list(set([k.split('_')[0] for k in det_data.keys()])))
            
            max_frame_logged = 1
            for frames in det_data.values():
                if frames:
                    max_frame_logged = max(max_frame_logged, frames[-1]['frame_count'])

            # --- UI IMPROVEMENT HERE ---
            st.markdown("#### Controls")
            
            # Use a horizontal radio button for instantaneous toggling
            selected_model = st.radio("Toggle Model:", available_models, horizontal=True)
            
            # Frame slider directly below it
            selected_frame = st.slider("Scrub Video Frame:", min_value=1, max_value=max_frame_logged, value=1)
            
            st.divider()
            # ---------------------------

            # Get the detections for the selected frame and model
            target_run_id = f"{selected_model}_Track-False_Frames-False"
            frame_detections = []
            
            if target_run_id in det_data:
                frame_data = next((f for f in det_data[target_run_id] if f['frame_count'] == selected_frame), None)
                if frame_data:
                    frame_detections = frame_data['detections']

            # Extract the frame via OpenCV
            cap = cv2.VideoCapture(VIDEO_FILE)
            cap.set(cv2.CAP_PROP_POS_FRAMES, selected_frame - 1) 
            ret, frame = cap.read()
            cap.release()

            if not ret:
                st.error("Could not read that frame from the video file.")
            else:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, _ = frame.shape

                for det in frame_detections:
                    label = det['label']
                    conf = det['confidence']
                    bbox = det['bbox'] 
                    
                    x1, y1 = int(bbox[0] * w), int(bbox[1] * h)
                    x2, y2 = int(bbox[2] * w), int(bbox[3] * h)
                    
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    
                    text = f"{label} {conf:.2f}"
                    (text_w, text_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                    cv2.rectangle(frame, (x1, y1 - 20), (x1 + text_w, y1), (0, 255, 0), -1)
                    cv2.putText(frame, text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

                st.image(frame, caption=f"Frame {selected_frame} | Model: {selected_model} | Detections: {len(frame_detections)}", use_container_width=True)