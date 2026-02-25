import streamlit as st
import cv2
import os
import shutil
import base64
import numpy as np
import concurrent.futures
import time
import requests  # 新增库
from openai import OpenAI
from PIL import Image
from io import BytesIO
from scenedetect import detect, ContentDetector
from fpdf import FPDF
from tenacity import retry, stop_after_attempt, wait_exponential
from sklearn.cluster import KMeans

# --- 1. 初始化设置 ---
st.set_page_config(page_title="AI 导演助手 Pro", layout="wide", page_icon="🎬")

# 尝试获取 API Key
api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

# --- 2. 自动下载字体逻辑 (解决上传限制问题) ---
def check_and_download_font(font_name="simhei.ttf"):
    """如果本地没有字体文件，则自动从网络下载"""
    if not os.path.exists(font_name):
        with st.spinner(f"正在首次下载中文字体 ({font_name})...这可能需要几十秒..."):
            try:
                # 这是一个公开的 SimHei 字体下载源
                url = "https://raw.githubusercontent.com/StellarCN/scp_zh/master/fonts/SimHei.ttf"
                r = requests.get(url, allow_redirects=True)
                with open(font_name, 'wb') as f:
                    f.write(r.content)
                st.success("✅ 字体下载成功！")
            except Exception as e:
                st.error(f"字体下载失败: {e}。PDF 中文可能会乱码。")

# 程序启动时检查一次字体
check_and_download_font()

# --- 3. PDF 生成类 ---
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
    
    # 字体加载逻辑
    has_chinese_font = False
    if os.path.exists(font_path):
        try:
            pdf.add_font("CustomFont", "", font_path, uni=True)
            pdf.set_font("CustomFont", size=11)
            has_chinese_font = True
        except Exception as e:
            st.warning(f"字体加载错误: {e}")
            pdf.set_font("Helvetica", size=11)
    else:
        # 如果下载失败，这里会作为保底
        pdf.set_font("Helvetica", size=11)

    for item in results:
        pdf.add_page()
        
        # 标题栏
        pdf.set_fill_color(240, 240, 240)
        title_font = "CustomFont" if has_chinese_font else "Helvetica"
        pdf.set_font(title_font, 'B', 12)
        pdf.cell(0, 10, f"  Shot {item['id']} | Time: {item['time']}", ln=True, fill=True)
        pdf.ln(5)
        
        # 图片
        try:
            pdf.image(item["path"], x=20, y=pdf.get_y(), w=170)
            pdf.ln(100)
        except:
            pdf.cell(0, 10, "[Image Error]", ln=True)

        # 文字内容
        pdf.set_font(title_font, '', 10)
        content = item['desc']
        
        if not has_chinese_font:
            content = "Chinese font missing. Text cannot be displayed."
            
        # 字符过滤
        safe_text = content.replace('\n', '  ').encode('utf-8', 'ignore').decode('utf-8')
        pdf.multi_cell(0, 7, txt=f"Director's Notes:\n{safe_text}")
        
    return pdf.output(dest='S').encode('latin-1')

# --- 4. 核心功能函数 ---
def extract_color_palette(image_path, color_count=5):
    try:
        img = Image.open(image_path).convert('RGB')
        img = img.resize((50, 50))
        ar = np.asarray(img)
        ar = ar.reshape(np.product(ar.shape[:2]), ar.shape[2])
        kmeans = KMeans(n_clusters=color_count, n_init=5).fit(ar)
        return kmeans.cluster_centers_.astype(int)
    except:
        return []

def render_color_bar(colors):
    cols = st.columns(len(colors))
    for i, rgb in enumerate(colors):
        hex_c = '#%02x%02x%02x' % tuple(rgb)
        cols[i].markdown(f'<div style="background-color:{hex_c};height:20px;border-radius:4px;" title="{hex_c}"></div>', unsafe_allow_html=True)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def analyze_with_ai(client_obj, image_path):
    with open(image_path, "rb") as f:
        b64_img = base64.b64encode(f.read()).decode('utf-8')
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

# --- 5. Streamlit UI ---
with st.sidebar:
    st.header("🎛️ 控制台")
    st.info(f"API 状态: {'✅ 已连接' if api_key else '❌ 未配置'}")
    sensitivity = st.slider("切分灵敏度", 10.0, 50.0, 27.0)
    uploaded_file = st.file_uploader("上传视频素材", type=["mp4", "mov"])
    st.divider()
    if st.button("🗑️ 清空重来"):
        if os.path.exists("shots"): shutil.rmtree("shots")
        st.cache_data.clear()
        st.session_state.clear()
        st.rerun()

st.title("🎬 AI 导演助手 Pro")

if not api_key:
    st.error("请先在 Streamlit Secrets 中配置 `OPENAI_API_KEY`")
    st.stop()
else:
    client = OpenAI(api_key=api_key)

if uploaded_file:
    video_path = "temp_video.mp4"
    with open(video_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if st.button("🚀 开始智能拉片", use_container_width=True):
        output_dir = "shots"
        if os.path.exists(output_dir): shutil.rmtree(output_dir)
        os.makedirs(output_dir)

        status_text = st.empty()
        progress_bar = st.progress(0)
        
        status_text.markdown("### ✂️ 正在进行智能切分...")
        scenes = detect(video_path, ContentDetector(threshold=sensitivity))
        cap = cv2.VideoCapture(video_path)
        
        shot_data = []
        for i, (start, end) in enumerate(scenes):
            cap.set(cv2.CAP_PROP_POS_FRAMES, start.get_frames() + 3)
            ret, frame = cap.read()
            if ret:
                img_path = f"{output_dir}/shot_{i+1:03d}.jpg"
                cv2.imwrite(img_path, frame)
                shot_data.append({"id": i+1, "path": img_path, "time": start.get_timecode(), "desc": "Waiting..."})
        cap.release()
        
        status_text.markdown(f"### 🤖 AI 正在分析 {len(shot_data)} 个镜头...")
        final_results = []
        placeholders = [st.empty() for _ in shot_data]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_shot = {executor.submit(analyze_with_ai, client, s["path"]): s for s in shot_data}
            for i, future in enumerate(concurrent.futures.as_completed(future_to_shot)):
                shot = future_to_shot[future]
                try:
                    res = future.result()
                    shot["desc"] = res
                    colors = extract_color_palette(shot["path"])
                    with placeholders[shot["id"]-1].container():
                        c1, c2 = st.columns([1, 2])
                        with c1:
                            st.image(shot["path"], use_container_width=True)
                            render_color_bar(colors)
                        with c2:
                            st.markdown(f"**Shot {shot['id']}**")
                            st.info(res)
                    final_results.append(shot)
                except Exception as e:
                    st.error(f"分析出错: {e}")
                progress_bar.progress((i + 1) / len(shot_data))
        
        final_results.sort(key=lambda x: x["id"])
        st.session_state['results'] = final_results
        status_text.success("✅ 完成！")

if 'results' in st.session_state and st.session_state['results']:
    st.divider()
    # 这里的 font_path="simhei.ttf" 将使用刚才代码自动下载的文件
    pdf_data = create_pdf(st.session_state['results'], font_path="simhei.ttf")
    st.download_button("📄 下载 PDF 报告", data=bytes(pdf_data), file_name="Storyboard_Report.pdf", mime="application/pdf", use_container_width=True)
