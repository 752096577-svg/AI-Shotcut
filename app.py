import streamlit as st
import cv2
import os
import shutil
import base64
import numpy as np
import concurrent.futures
import time
from openai import OpenAI
from PIL import Image
from io import BytesIO
from scenedetect import detect, ContentDetector
from fpdf import FPDF
from tenacity import retry, stop_after_attempt, wait_exponential
from sklearn.cluster import KMeans

# --- 1. 初始化设置 ---
st.set_page_config(page_title="AI 导演助手 Pro", layout="wide", page_icon="🎬")

# 尝试获取 API Key (支持 Secrets 和环境变量)
api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

# --- 2. 专业 PDF 生成类 (带字体回退保护) ---
class DirectorReport(FPDF):
    def header(self):
        if self.page_no() == 1:
            self.set_font("Helvetica", 'B', 20)
            self.cell(0, 15, "AI Storyboard Analysis Report", ln=True, align='C')
            self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", 'I', 8)
        self.cell(0, 10, f"Page {self.page_no()}", align='C')

def create_pdf(results, font_path="simhei.ttf"):
    pdf = DirectorReport()
    
    # 字体加载逻辑：如果有中文字体就用，没有就回退到英文以免报错
    has_chinese_font = False
    if os.path.exists(font_path):
        try:
            pdf.add_font("CustomFont", "", font_path, uni=True)
            pdf.set_font("CustomFont", size=11)
            has_chinese_font = True
        except Exception as e:
            st.warning(f"字体加载失败: {e}，将使用默认字体(不支持中文)。")
            pdf.set_font("Helvetica", size=11)
    else:
        st.warning(f"未检测到 {font_path} 文件。PDF 中的中文可能无法显示。请上传字体文件到 GitHub。")
        pdf.set_font("Helvetica", size=11)

    for item in results:
        pdf.add_page()
        
        # 标题栏
        pdf.set_fill_color(240, 240, 240)
        # 如果没有中文字体，标题用标准字体
        title_font = "CustomFont" if has_chinese_font else "Helvetica"
        pdf.set_font(title_font, 'B', 12)
        pdf.cell(0, 10, f"  Shot {item['id']} | Time: {item['time']}", ln=True, fill=True)
        pdf.ln(5)
        
        # 图片
        try:
            # 保持图片比例，宽度设为170
            pdf.image(item["path"], x=20, y=pdf.get_y(), w=170)
            pdf.ln(100) # 图片占位高度
        except:
            pdf.cell(0, 10, "[Image Error]", ln=True)

        # 文字内容
        pdf.set_font(title_font, '', 10)
        content = item['desc']
        
        # 如果没有中文字体，强制转换内容以防报错
        if not has_chinese_font:
            content = "Chinese font missing. Please upload simhei.ttf to view text."
            
        # 过滤掉可能导致 FPDF 崩溃的特殊字符
        safe_text = content.replace('\n', '  ').encode('utf-8', 'ignore').decode('utf-8')
        pdf.multi_cell(0, 7, txt=f"Director's Notes:\n{safe_text}")
        
    return pdf.output(dest='S').encode('latin-1')

# --- 3. 核心功能函数 ---
def extract_color_palette(image_path, color_count=5):
    """提取图片主色调 (使用 KMeans 聚类)"""
    try:
        img = Image.open(image_path).convert('RGB')
        img = img.resize((50, 50)) # 缩小以加快速度
        ar = np.asarray(img)
        ar = ar.reshape(np.product(ar.shape[:2]), ar.shape[2])
        kmeans = KMeans(n_clusters=color_count, n_init=5).fit(ar)
        return kmeans.cluster_centers_.astype(int)
    except:
        return []

def render_color_bar(colors):
    """在UI中渲染 HTML 色条"""
    cols = st.columns(len(colors))
    for i, rgb in enumerate(colors):
        hex_c = '#%02x%02x%02x' % tuple(rgb)
        cols[i].markdown(f'<div style="background-color:{hex_c};height:20px;border-radius:4px;" title="{hex_c}"></div>', unsafe_allow_html=True)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def analyze_with_ai(client_obj, image_path):
    """AI分析，带自动重试机制"""
    with open(image_path, "rb") as f:
        b64_img = base64.b64encode(f.read()).decode('utf-8')
    
    # 稍微延迟避免并发限制
    time.sleep(np.random.uniform(0.1, 0.5))
    
    response = client_obj.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "你是电影摄影指导。请简练分析此画面的：1.构图与景别 2.光影色彩 3.叙事张力。请用中文回答。"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
        ]}],
        max_tokens=300
    )
    return response.choices[0].message.content

# --- 4. Streamlit UI 逻辑 ---
with st.sidebar:
    st.header("🎛️ 控制台")
    st.info(f"API 状态: {'✅ 已连接' if api_key else '❌ 未配置'}")
    
    sensitivity = st.slider("切分灵敏度 (Threshold)", 10.0, 50.0, 27.0, help="数值越小，切分越细致")
    uploaded_file = st.file_uploader("上传视频素材 (MP4/MOV)", type=["mp4", "mov"])
    
    st.divider()
    if st.button("🗑️ 清空缓存重来"):
        if os.path.exists("shots"): shutil.rmtree("shots")
        st.cache_data.clear()
        st.session_state.clear()
        st.rerun()

st.title("🎬 AI 导演助手 Pro")
st.markdown("Automatic Storyboard & Cinematography Analysis")

# 检查 API Key
if not api_key:
    st.error("请先在 Streamlit Secrets 中配置 `OPENAI_API_KEY`")
    st.stop()
else:
    client = OpenAI(api_key=api_key)

if uploaded_file:
    # 保存临时文件
    video_path = "temp_video.mp4"
    with open(video_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    # 只有当点击按钮时才开始处理
    if st.button("🚀 开始智能拉片 (AI Analysis)", use_container_width=True):
        output_dir = "shots"
        if os.path.exists(output_dir): shutil.rmtree(output_dir)
        os.makedirs(output_dir)

        # 1. 视频切分
        status_text = st.empty()
        progress_bar = st.progress(0)
        
        status_text.markdown("### ✂️ 第一步：正在进行智能场面调度识别...")
        scenes = detect(video_path, ContentDetector(threshold=sensitivity))
        cap = cv2.VideoCapture(video_path)
        
        shot_data = []
        for i, (start, end) in enumerate(scenes):
            # 获取每个镜头的第 3 帧（避开转场黑屏）
            cap.set(cv2.CAP_PROP_POS_FRAMES, start.get_frames() + 3)
            ret, frame = cap.read()
            if ret:
                img_path = f"{output_dir}/shot_{i+1:03d}.jpg"
                cv2.imwrite(img_path, frame)
                shot_data.append({
                    "id": i+1,
                    "path": img_path, 
                    "time": start.get_timecode(),
                    "desc": "Waiting..."
                })
        cap.release()
        
        # 2. AI 并发分析
        status_text.markdown(f"### 🤖 第二步：AI 正在并发分析 {len(shot_data)} 个镜头...")
        
        final_results = []
        # 创建占位符容器，用于实时显示
        placeholders = [st.empty() for _ in shot_data]
        
        # 使用线程池并发处理 (Max workers=3 以免触发 API 速率限制)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            # 提交任务
            future_to_shot = {executor.submit(analyze_with_ai, client, s["path"]): s for s in shot_data}
            
            for i, future in enumerate(concurrent.futures.as_completed(future_to_shot)):
                shot = future_to_shot[future]
                try:
                    # 获取 AI 结果
                    analysis_text = future.result()
                    shot["desc"] = analysis_text
                    
                    # 提取颜色
                    colors = extract_color_palette(shot["path"])
                    
                    # 实时渲染到界面
                    with placeholders[shot["id"]-1].container():
                        c1, c2 = st.columns([1, 2])
                        with c1:
                            st.image(shot["path"], use_container_width=True)
                            render_color_bar(colors)
                        with c2:
                            st.markdown(f"**Shot {shot['id']} - {shot['time']}**")
                            st.info(analysis_text)
                    
                    final_results.append(shot)
                except Exception as e:
                    st.error(f"镜头 {shot['id']} 分析出错: {e}")
                
                # 更新进度条
                progress_bar.progress((i + 1) / len(shot_data))
        
        # 排序并保存结果
        final_results.sort(key=lambda x: x["id"])
        st.session_state['results'] = final_results
        status_text.success("✅ 全部分析完成！您可以下载报告了。")

# --- 5. 结果导出区 ---
if 'results' in st.session_state and st.session_state['results']:
    st.divider()
    col_a, col_b = st.columns([1, 3])
    with col_a:
        st.markdown("### 📥 导出报告")
    with col_b:
        # 只有存在 simhei.ttf 才能完美支持中文，否则会有警告
        pdf_data = create_pdf(st.session_state['results'], font_path="simhei.ttf")
        st.download_button(
            label="📄 下载 PDF 分镜脚本 (含导演笔记)",
            data=bytes(pdf_data),
            file_name="AI_Director_Storyboard.pdf",
            mime="application/pdf",
            use_container_width=True
        )
