import streamlit as st
import os
import cv2
import shutil
from scenedetect import detect, ContentDetector
from PIL import Image

# 1. 软件界面美化
st.set_page_config(page_title="ShotCut 分镜大师", layout="wide", initial_sidebar_state="expanded")

# 自定义 CSS 样式，增加软件质感
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #FF4B4B; color: white; }
    .shot-card { border: 1px solid #ddd; padding: 10px; border-radius: 10px; background-color: white; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# 2. 核心功能函数
def process_video_to_shots(video_path, threshold):
    output_dir = "extracted_shots"
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    # 物理镜头分割
    scenes = detect(video_path, ContentDetector(threshold=threshold))
    
    cap = cv2.VideoCapture(video_path)
    shot_data = []
    
    for i, (start_time, end_time) in enumerate(scenes):
        # 在镜头开始后 3 帧取图，确保画面稳定
        target_frame = start_time.get_frames() + 3 
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        success, frame = cap.read()
        
        if success:
            img_name = f"shot_{i+1:03d}.jpg"
            img_path = os.path.join(output_dir, img_name)
            cv2.imwrite(img_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            shot_data.append({
                "id": i+1,
                "path": img_path,
                "time": start_time.get_timecode()
            })
    cap.release()
    return shot_data

# 3. App 承载体结构
st.title("🎬 ShotCut 分镜自动提取软件")

# 创建两个标签页：处理中心、分镜库
tab1, tab2 = st.tabs(["📥 视频处理中心", "🖼️ 分镜管理库"])

with tab1:
    col_u1, col_u2 = st.columns([2, 1])
    with col_u1:
        uploaded_file = st.file_uploader("将视频文件丢入此处", type=["mp4", "mov", "mkv"])
    with col_u2:
        st.write("🔧 切分参数")
        sensitivity = st.slider("切分灵敏度", 10.0, 50.0, 27.0, help="数值越低，切得越细")
        
    if uploaded_file:
        with open("temp_video.mp4", "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        if st.button("开始自动识别并提取分镜"):
            with st.spinner("正在进行物理镜头切分..."):
                st.session_state['shots'] = process_video_to_shots("temp_video.mp4", sensitivity)
                st.success(f"处理完成！识别到 {len(st.session_state['shots'])} 个镜头。请前往“分镜管理库”查看。")

with tab2:
    if 'shots' in st.session_state and st.session_state['shots']:
        st.subheader(f"共计 {len(st.session_state['shots'])} 组分镜")
        
        # 每行显示 3 组分镜，更像专业软件布局
        for i in range(0, len(st.session_state['shots']), 3):
            cols = st.columns(3)
            for j in range(3):
                if i + j < len(st.session_state['shots']):
                    shot = st.session_state['shots'][i + j]
                    with cols[j]:
                        st.image(shot['path'], use_container_width=True)
                        st.caption(f"镜头 #{shot['id']} | 时间点: {shot['time']}")
    else:
        st.info("暂无数据，请先在“处理中心”上传视频并执行提取。")
        