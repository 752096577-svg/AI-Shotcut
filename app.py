import streamlit as st
import os
import cv2
import shutil
import zipfile
from io import BytesIO
from PIL import Image
from scenedetect import detect, ContentDetector

# 1. 设置页面
st.set_page_config(page_title="AI 视频分镜专家", layout="wide")
st.title("🎞️ AI 视频分镜提取与导出")

# 2. 导出 PDF 的核心逻辑 (使用 Pillow 转换)
def create_pdf(shot_images):
    pdf_buffer = BytesIO()
    # 将 OpenCV 图像(BGR)转换为 PIL 图像(RGB)并存入列表
    pil_images = []
    for img_path in shot_images:
        img = Image.open(img_path).convert("RGB")
        pil_images.append(img)
    
    if pil_images:
        # 将第一张图作为 PDF 起始，其余图追加
        pil_images[0].save(pdf_buffer, format="PDF", save_all=True, append_images=pil_images[1:])
    pdf_buffer.seek(0)
    return pdf_buffer

# 3. 导出 ZIP 的核心逻辑
def create_zip(folder_path):
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.endswith(('.jpg', '.png')):
                    zf.write(os.path.join(root, file), file)
    zip_buffer.seek(0)
    return zip_buffer

# --- 侧边栏：操作与下载 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    sensitivity = st.slider("分镜灵敏度", 10.0, 50.0, 27.0)
    uploaded_file = st.file_uploader("丢入视频文件", type=["mp4", "mov"])
    
    if st.button("🧼 清理所有数据"):
        if os.path.exists("extracted_shots"): shutil.rmtree("extracted_shots")
        st.rerun()

# --- 主页面逻辑 ---
if uploaded_file:
    video_path = "temp_video.mp4"
    with open(video_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if st.button("🚀 开始精准提取并生成报告", use_container_width=True):
        output_dir = "extracted_shots"
        if os.path.exists(output_dir): shutil.rmtree(output_dir)
        os.makedirs(output_dir)

        with st.spinner("正在识别镜头并切分..."):
            # 使用 ContentDetector
            scenes = detect(video_path, ContentDetector(threshold=sensitivity))
            cap = cv2.VideoCapture(video_path)
            shot_paths = []
            
            for i, (start_time, end_time) in enumerate(scenes):
                target_frame = start_time.get_frames() + 3
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                success, frame = cap.read()
                if success:
                    p = f"{output_dir}/shot_{i+1:03d}.jpg"
                    cv2.imwrite(p, frame)
                    shot_paths.append(p)
            cap.release()
            st.session_state['shot_paths'] = shot_paths
            st.success(f"完成！共提取 {len(shot_paths)} 个镜头。")

    # --- 导出按钮区域 ---
    if 'shot_paths' in st.session_state:
        st.divider()
        col1, col2 = st.columns(2)
        
        with col1:
            pdf_data = create_pdf(st.session_state['shot_paths'])
            st.download_button("📂 下载 PDF 分镜表", data=pdf_data, file_name="storyboard.pdf", mime="application/pdf")
            
        with col2:
            zip_data = create_zip("extracted_shots")
            st.download_button("📦 下载分镜图打包 (ZIP)", data=zip_data, file_name="all_shots.zip", mime="application/zip")

        # 预览图展示
        st.subheader("分镜预览")
        cols = st.columns(4)
        for idx, img_p in enumerate(st.session_state['shot_paths']):
            with cols[idx % 4]:
                st.image(img_p, caption=f"镜头 {idx+1}")
