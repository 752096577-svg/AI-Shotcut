import streamlit as st
import cv2
import os
import shutil
import numpy as np
import requests
from PIL import Image
from scenedetect import detect, ContentDetector
from fpdf import FPDF

# --- 1. 基础配置 ---
st.set_page_config(page_title="自动分镜提取工具 (本地版)", layout="wide", page_icon="🎬")

# 自动下载中文字体 (仅用于 PDF 标题，防止乱码)
def check_and_download_font(font_name="simhei.ttf"):
    if not os.path.exists(font_name):
        with st.spinner(f"正在配置字体环境..."):
            try:
                url = "https://raw.githubusercontent.com/StellarCN/scp_zh/master/fonts/SimHei.ttf"
                r = requests.get(url, allow_redirects=True)
                with open(font_name, 'wb') as f:
                    f.write(r.content)
            except:
                pass
check_and_download_font()

# --- 2. 图像处理 (核心：三帧拼合) ---
def create_motion_strip(img_paths, output_path):
    """
    将 [开始, 中间, 结束] 三张图拼合成一张宽图。
    这是不需要 AI 也能看懂运镜的神器。
    """
    images = [Image.open(p) for p in img_paths]
    widths, heights = zip(*(i.size for i in images))
    
    total_width = sum(widths)
    max_height = max(heights)
    
    new_im = Image.new('RGB', (total_width, max_height))
    
    x_offset = 0
    for im in images:
        new_im.paste(im, (x_offset, 0))
        x_offset += im.size[0]
    
    new_im.save(output_path)
    return output_path

# --- 3. PDF 生成类 (专为手写笔记优化) ---
class DirectorReport(FPDF):
    def header(self):
        if self.page_no() == 1:
            self.set_font("Helvetica", 'B', 20)
            self.cell(0, 15, "Storyboard Motion Report", ln=True, align='C')
            self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", 'I', 8)
        self.cell(0, 10, f"Page {self.page_no()}", align='C')

def create_pdf(results, font_path="simhei.ttf"):
    pdf = DirectorReport()
    
    # 字体设置
    has_chinese = False
    if os.path.exists(font_path):
        try:
            pdf.add_font("CustomFont", "", font_path, uni=True)
            pdf.set_font("CustomFont", size=10)
            has_chinese = True
        except:
            pdf.set_font("Helvetica", size=10)
    else:
        pdf.set_font("Helvetica", size=10)

    for item in results:
        pdf.add_page()
        
        # 1. 标题行 (镜头号 + 时间 + 时长)
        pdf.set_fill_color(230, 230, 230)
        title_font = "CustomFont" if has_chinese else "Helvetica"
        pdf.set_font(title_font, 'B', 14)
        pdf.cell(0, 12, f"  Shot {item['id']} | Time: {item['time']} | Duration: {item['duration']:.1f}s", ln=True, fill=True)
        pdf.ln(5)
        
        # 2. 运镜拼图 (视觉核心)
        try:
            pdf.image(item["strip_path"], x=10, y=pdf.get_y(), w=190) 
            pdf.ln(65) # 预留图片高度
        except:
            pdf.ln(65)
        
        # 3. 辅助标签
        pdf.set_font("Helvetica", 'I', 8)
        pdf.cell(63, 5, "Start", align='C')
        pdf.cell(63, 5, "Mid", align='C')
        pdf.cell(63, 5, "End", align='C')
        pdf.ln(10)

        # 4. 手写笔记区 (既然没有AI，就留白给导演手写)
        pdf.set_font(title_font, '', 10)
        pdf.set_draw_color(180, 180, 180) # 灰色线条
        
        pdf.cell(0, 8, "Notes / Action / Dialogue:", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y()) # 横线
        pdf.ln(8)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y()) # 横线
        pdf.ln(8)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y()) # 横线
        
    return pdf.output(dest='S').encode('latin-1')

# --- 4. UI 界面 ---
with st.sidebar:
    st.header("🎛️ 提取参数设置")
    
    st.info("💡 本模式无需 API Key，纯本地运算，速度极快。")
    
    # 核心参数
    sensitivity = st.slider("切分灵敏度 (数值越小切得越碎)", 5.0, 50.0, 25.0)
    min_duration = st.slider("防抖时长 (秒)", 0.1, 2.0, 1.0, help="短于此时间的画面变化不切分，防止运镜被切碎。")

    uploaded_file = st.file_uploader("上传视频素材 (MP4/MOV)", type=["mp4", "mov"])
    
    st.divider()
    if st.button("🗑️ 清空所有数据"):
        if os.path.exists("shots"): shutil.rmtree("shots")
        st.session_state.clear()
        st.rerun()

# --- 5. 主程序逻辑 ---
st.title("🎬 自动分镜提取工具 (纯净版)")

if uploaded_file:
    video_path = "temp_video.mp4"
    with open(video_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if st.button("🚀 开始提取分镜", use_container_width=True):
        output_dir = "shots"
        if os.path.exists(output_dir): shutil.rmtree(output_dir)
        os.makedirs(output_dir)

        # A. 智能切分
        st_text = st.empty()
        st_bar = st.progress(0)
        st_text.markdown("### ✂️ 正在逐帧分析视频...")
        
        # 计算帧数
        min_scene_frames = int(min_duration * 24)
        
        # 调用 PySceneDetect
        scenes = detect(video_path, ContentDetector(threshold=sensitivity, min_scene_len=min_scene_frames))
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        shot_data = []
        total_scenes = len(scenes)
        
        for i, (start, end) in enumerate(scenes):
            # 获取 Start, Mid, End 三帧
            frames_idx = [
                start.get_frames() + 5,
                int((start.get_frames() + end.get_frames()) / 2),
                end.get_frames() - 5
            ]
            
            temp_paths = []
            for fid in frames_idx:
                cap.set(cv2.CAP_PROP_POS_FRAMES, fid)
                ret, frame = cap.read()
                if ret:
                    # 适当压缩图片，减小 PDF 体积
                    frame = cv2.resize(frame, (0, 0), fx=0.6, fy=0.6)
                    p = f"{output_dir}/temp_{i}_{fid}.jpg"
                    cv2.imwrite(p, frame)
                    temp_paths.append(p)
            
            # 只有凑齐 3 帧才生成记录
            if len(temp_paths) == 3:
                strip_path = f"{output_dir}/shot_{i+1:03d}_strip.jpg"
                create_motion_strip(temp_paths, strip_path)
                
                duration = (end.get_frames() - start.get_frames()) / fps
                
                shot_data = [] # 修正变量作用域
                # 重新读取 st.session_state 如果需要，或者直接追加
                
                # 实时展示
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.image(strip_path, caption=f"Shot {i+1}", use_container_width=True)
                with c2:
                    st.markdown(f"**时间码**: {start.get_timecode()}")
                    st.markdown(f"**时长**: {duration:.1f}s")
                
                # 保存数据供 PDF 使用
                st.session_state.setdefault('results', []).append({
                    "id": i+1,
                    "strip_path": strip_path,
                    "time": start.get_timecode(),
                    "duration": duration
                })
            
            st_bar.progress((i + 1) / total_scenes)

        cap.release()
        st_text.success(f"✅ 提取完成！共识别 {len(scenes)} 个镜头。")

# --- 6. 导出区 ---
if 'results' in st.session_state and st.session_state['results']:
    st.divider()
    
    # 纯净版 PDF 导出
    pdf_data = create_pdf(st.session_state['results'], font_path="simhei.ttf")
    
    st.download_button(
        label="📄 下载分镜表 (PDF)",
        data=bytes(pdf_data),
        file_name="Storyboard_Motion_Report.pdf",
        mime="application/pdf",
        use_container_width=True
    )
