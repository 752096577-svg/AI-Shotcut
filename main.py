import os
import cv2
from scenedetect import detect, AdaptiveDetector, ContentDetector

# --- 1. 设置变量 ---
video_filename = "test.mp4"
output_folder = "extracted_shots"

def run_storyboard():
    # --- 2. 创建存放图片的目录 ---
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"已创建文件夹: {output_folder}")

    # --- 3. 自动检测镜头边界 ---
    print("正在进行精细化分镜扫描，请稍候...")
    
    # 修改点：将 min_scene_len 降低到 1，捕捉极细微的镜头切换
    # 如果 AdaptiveDetector 效果不理想，可以解注下一行改用 ContentDetector
    scenes = detect(video_filename, AdaptiveDetector(min_scene_len=1))
    
    print(f"分析完成！一共发现了 {len(scenes)} 个细致分镜。")

    # --- 4. 抽取每个镜头的画面 ---
    cap = cv2.VideoCapture(video_filename)
    
    for i, scene in enumerate(scenes):
        # 获取每个镜头开始的第一帧位置
        start_frame = scene[0].get_frames()
        
        # 告诉电脑：把进度条拉到这一帧
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        success, frame = cap.read()
        
        if success:
            # 给图片命名
            img_name = f"shot_{i+1:03d}.jpg"
            save_path = os.path.join(output_folder, img_name)
            
            # 提高保存质量：[cv2.IMWRITE_JPEG_QUALITY, 95] 确保分镜更细致清晰
            cv2.imwrite(save_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            print(f"成功导出: {img_name}")

    cap.release()
    print("\n所有精细分镜已全部完成！请去 extracted_shots 文件夹查看。")

# 启动程序
if __name__ == "__main__":
    run_storyboard()