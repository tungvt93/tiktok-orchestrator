import os
import subprocess
import math
import json
import textwrap

def get_video_duration(input_file):
    """Lấy thời lượng video (giây) bằng ffprobe."""
    cmd = [
        'ffprobe', 
        '-v', 'error', 
        '-show_entries', 'format=duration', 
        '-of', 'default=noprint_wrappers=1:nokey=1', 
        input_file
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return float(result.stdout.strip())

def process_video_segment(input_file, output_file, start_time, duration, title_text):
    """
    Xử lý một đoạn video với các yêu cầu:
    1. Zoom 180%
    2. Nền mờ (blur) trên/dưới cho tỷ lệ 9:16
    3. Tốc độ 1.2x
    4. Lật ngang
    5. Chỉnh màu nhẹ
    """
    
    # Xử lý text để tự động xuống dòng (khoảng 22 ký tự 1 dòng) và căn giữa
    lines = textwrap.wrap(title_text, width=22)
    max_len = max((len(line) for line in lines), default=0)
    centered_lines = [line.center(max_len) for line in lines]
    wrapped_text = "\n".join(centered_lines)
    
    # FFMPEG xử lý text nhiều dòng tốt nhất khi đọc từ file
    with open("temp_title.txt", "w", encoding="utf-8") as f:
        f.write(wrapped_text)

    # Độ phân giải đích (9:16)
    target_width = 1080
    target_height = 1920
    
    # 1.2x speed
    video_speed = 1.3
    audio_speed = 1.3
    
    # Tính toán filter
    # setpts và atempo cho tốc độ
    # hflip cho lật ngang
    # eq cho chỉnh màu (tăng contrast và saturation nhẹ)
    
    # Filter graph phức tạp của ffmpeg
    filter_complex = (
        f"[0:v]trim=start={start_time}:duration={duration},setpts=PTS/{video_speed},"
        f"hflip,eq=contrast=1.1:saturation=1.4:brightness=0.06,colorbalance=rm=0.08:gm=0.08:bm=-0.15[v_base]; "
        
        # Tạo luồng cho nền (mờ)
        f"[v_base]split=2[v_bg][v_fg]; "
        
        # Xử lý nền: scale để lấp đầy 9:16, cắt phần thừa, làm mờ
        f"[v_bg]scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
        f"crop={target_width}:{target_height},boxblur=luma_radius=25:luma_power=2[bg]; "
        
        # Xử lý video chính: zoom 180% (tức là scale=iw*1.8:ih*1.8)
        # Tuy nhiên, để vừa với khung hình, ta scale theo width của khung 9:16 rồi zoom 1.8
        # Chiều rộng fit = 1080. Zoom 180% = 1080 * 1.8 = 1944.
        f"[v_fg]scale={target_width}:-1,scale=iw*1.8:ih*1.8[fg]; "
        
        # Overlay video chính lên nền
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vid_merged]; "
        
        # Thêm text ở phần trên cùng của video, đọc từ file để hỗ trợ xuống dòng
        # fontcolor=lime (xanh sáng neon), không viền, không bóng đổ
        f"[vid_merged]drawtext=textfile='temp_title.txt':fontcolor=#22f158:fontsize=80:line_spacing=15:x=(w-text_w)/2:y=200[outv]; "
        
        # Xử lý âm thanh
        f"[0:a]atrim=start={start_time}:duration={duration},atempo={audio_speed}[outa]"
    )

    cmd = [
        'ffmpeg',
        '-y', # Ghi đè file
        '-i', input_file,
        '-filter_complex', filter_complex,
        '-map', '[outv]',
        '-map', '[outa]',
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '128k',
        output_file
    ]
    
    print(f"Đang render {output_file} (từ giây {start_time} - độ dài {duration}s)...")
    subprocess.run(cmd)
    print(f"Hoàn thành: {output_file}")

def main():
    input_video = "Ep. 24 - A New Hire.mp4" # THAY ĐỔI TÊN VIDEO CỦA BẠN Ở ĐÂY
    # Tự động lấy tên file (không có đuôi .mp4) làm text hiển thị
    title_text = os.path.splitext(os.path.basename(input_video))[0]
    
    if not os.path.exists(input_video):
        print(f"Không tìm thấy file {input_video}. Vui lòng sửa tên file trong script.")
        return

    total_duration = get_video_duration(input_video)
    segment_duration = 120 # 2 phút = 120 giây
    filename, ext = os.path.splitext(input_video)
    
    if total_duration > 180: # Dài hơn 3 phút (180 giây)
        num_segments = math.ceil(total_duration / segment_duration)
        print(f"Video dài {total_duration:.2f} giây (> 3 phút). Sẽ được chia làm {num_segments} phần.")
        
        for i in range(num_segments):
            start_time = i * segment_duration
            # Đảm bảo phần cuối không vượt quá tổng thời lượng
            duration = min(segment_duration, total_duration - start_time)
            output_name = f"{filename}_part{i+1}{ext}"
            process_video_segment(input_video, output_name, start_time, duration, title_text)
    else:
        print(f"Video dài {total_duration:.2f} giây (<= 3 phút). Sẽ không cắt, giữ nguyên 1 video.")
        output_name = f"{filename}_processed{ext}"
        process_video_segment(input_video, output_name, 0, total_duration, title_text)

if __name__ == "__main__":
    main()
