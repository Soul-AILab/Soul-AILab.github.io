# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# 语音转录可视化播放器（稳健版）
# 功能：
# 1. 加载 JSONL 数据，解析带时间戳的转录结果
# 2. 左侧播放视频/音频，右侧同步高亮显示对应语句
# 3. 绿色高亮：当前播放时间对应的语句
# 4. 橙色高亮：多人同时说话（时间重叠）的语句
# 5. 支持点击语句跳转播放位置
# 6. 自动检测多种转录格式（hyp / moss_qwen_format_text / utterance）

# 正则规则：\[(\d{2}:\d{2}\.\d{2})\s*-->\s*(\d{2}:\d{2}\.\d{2})\]\s*(Speaker \d+):\s*(.*)
# """

# import json
# import re
# import os
# import gradio as gr
# import tempfile

# from pathlib import Path
# from typing import List, Dict, Optional, Tuple


# # ─────────────────────────── 数据解析 ───────────────────────────

# def parse_time_to_seconds(time_str: str) -> float:
#     """
#     解析时间字符串为秒数，支持多种格式：
#     - "MM:SS.ss"  （如 "00:01.49"）
#     - "SS.ss"     （如 "1.49"）
#     - "HH:MM:SS.ss"
#     """
#     time_str = time_str.strip()
#     if not time_str:
#         return 0.0
#     try:
#         parts = time_str.split(':')
#         if len(parts) == 1:
#             # 纯秒数: "1.49"
#             return float(parts[0])
#         elif len(parts) == 2:
#             # MM:SS.ss
#             return float(parts[0]) * 60 + float(parts[1])
#         elif len(parts) == 3:
#             # HH:MM:SS.ss
#             return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
#     except (ValueError, AttributeError):
#         pass
#     return 0.0


# def parse_hyp_line(line: str) -> Optional[Dict]:
#     """
#     解析单行转录，使用用户指定的严格正则规则：

#     输入格式: [00:00.87 --> 00:01.49] Speaker 1: 现在

#     正则: \[(\d{2}:\d{2}\.\d{2})\s*-->\s*(\d{2}:\d{2}\.\d{2})\]\s*(Speaker \d+):\s*(.*)
#     """
#     pattern = re.compile(
#         r'\[(\d{2}:\d{2}\.\d{2})\s*-->\s*(\d{2}:\d{2}\.\d{2})\]\s*(Speaker \d+):\s*(.*)'
#     )

#     match = pattern.match(line.strip())
#     if not match:
#         return None

#     start_str, end_str, speaker, text = match.groups()
#     return {
#         'start': parse_time_to_seconds(start_str),
#         'end': parse_time_to_seconds(end_str),
#         'speaker': speaker.strip(),
#         'text': text.strip(),
#         'speaker_id': speaker.strip().replace(' ', '_')
#     }


# def parse_hyp_content(hyp: str) -> List[Dict]:
#     """解析完整的 hyp 字符串，返回语句列表"""
#     if not hyp or hyp.strip().lower() in ('none', 'null', ''):
#         return []

#     segments = []
#     for line in hyp.strip().split('\n'):
#         line = line.strip()
#         if not line:
#             continue
#         seg = parse_hyp_line(line)
#         if seg:
#             segments.append(seg)

#     segments.sort(key=lambda x: x['start'])
#     return segments


# # 🔧 新增：从 utterance 列表解析（作为 fallback）
# def parse_utterance_list(utterances: list) -> List[Dict]:
#     """
#     从 utterance 字段（list of dict）解析转录段落。
#     每个 item 形如: {"spk_id": 916691059, "start": 5.69, "end": 6.44, "text": "呵呵", ...}
#     """
#     if not utterances or not isinstance(utterances, list):
#         return []

#     segments = []
#     # 收集所有 spk_id 用于分配 Speaker 编号
#     spk_ids_seen = {}
#     for utt in utterances:
#         if not isinstance(utt, dict):
#             continue
#         spk_id = utt.get('spk_id', 'unknown')
#         if spk_id not in spk_ids_seen:
#             spk_ids_seen[spk_id] = f"Speaker {len(spk_ids_seen) + 1}"

#     for utt in utterances:
#         if not isinstance(utt, dict):
#             continue
#         try:
#             spk_id = utt.get('spk_id', 'unknown')
#             speaker = spk_ids_seen.get(spk_id, f"Speaker ?")
#             seg = {
#                 'start': float(utt.get('start', 0)),
#                 'end': float(utt.get('end', 0)),
#                 'speaker': speaker,
#                 'text': str(utt.get('text', '')).strip(),
#                 'speaker_id': speaker.replace(' ', '_'),
#             }
#             if seg['text']:
#                 segments.append(seg)
#         except (ValueError, TypeError):
#             continue

#     segments.sort(key=lambda x: x['start'])
#     return segments


# # 🔧 新增：智能提取转录段落，按优先级尝试多个字段
# def extract_segments(item: Dict) -> List[Dict]:
#     """
#     按以下优先级尝试解析转录内容：
#     1. moss_qwen_format_text（通常质量最高、分句最细）
#     2. hyp
#     3. utterance（list of dict，兜底方案）
#     """
#     # 优先级 1: moss_qwen_format_text
#     text = item.get('moss_qwen_format_text', '')
#     if text and str(text).strip().lower() not in ('none', 'null', ''):
#         segments = parse_hyp_content(str(text))
#         if segments:
#             return segments

#     # 优先级 2: hyp
#     text = item.get('hyp', '')
#     if text and str(text).strip().lower() not in ('none', 'null', ''):
#         segments = parse_hyp_content(str(text))
#         if segments:
#             return segments

#     # 优先级 3: utterance (list)
#     utt_list = item.get('utterance', [])
#     if utt_list:
#         segments = parse_utterance_list(utt_list)
#         if segments:
#             return segments

#     return []


# def detect_overlaps(segments: List[Dict], tolerance: float = 0.1) -> List[bool]:
#     """
#     检测每个语句是否与其他语句时间重叠（多人同时说话）
#     返回布尔列表，True 表示该语句有重叠
#     """
#     overlaps = [False] * len(segments)
#     for i, seg_i in enumerate(segments):
#         for j, seg_j in enumerate(segments):
#             if i == j:
#                 continue
#             if seg_i['start'] < seg_j['end'] - tolerance and seg_i['end'] > seg_j['start'] + tolerance:
#                 overlaps[i] = True
#                 break
#     return overlaps


# # ─────────────────────────── HTML 生成 ───────────────────────────

# def format_time(seconds: float) -> str:
#     """格式化时间为 MM:SS 格式"""
#     m = int(seconds // 60)
#     s = int(seconds % 60)
#     return f"{m:02d}:{s:02d}"


# def escape_html(text: str) -> str:
#     """转义 HTML 特殊字符"""
#     return (text.replace('&', '&amp;')
#                .replace('<', '&lt;')
#                .replace('>', '&gt;')
#                .replace('"', '&quot;'))


# def generate_transcript_html(segments: List[Dict], overlaps: List[bool],
#                              current_time: float = -1, highlight_idx: int = -1) -> str:
#     """
#     生成转录内容的 HTML，支持动态高亮
#     """
#     speaker_colors = {}
#     base_colors = ['#4fc3f7', '#81c784', '#ffb74d', '#ba68c8', '#e57373', '#64b5f6',
#                    '#f06292', '#aed581', '#ffcc80', '#90caf9']  # 🔧 扩充颜色池

#     if not segments:
#         return '<div class="empty">⚠️ 未解析到转录内容（hyp / moss_qwen_format_text / utterance 均为空或格式不匹配）</div>'

#     html_parts = []

#     for idx, seg in enumerate(segments):
#         spk = seg['speaker']
#         if spk not in speaker_colors:
#             speaker_colors[spk] = base_colors[len(speaker_colors) % len(base_colors)]

#         is_current = (idx == highlight_idx)
#         is_overlap = overlaps[idx] if idx < len(overlaps) else False

#         classes = ['transcript-line']
#         if is_current:
#             classes.append('current')
#         if is_overlap:
#             classes.append('overlap')

#         html_parts.append(f'''
#         <div class="{' '.join(classes)}"
#              data-idx="{idx}"
#              data-start="{seg['start']:.2f}"
#              style="--spk-color: {speaker_colors[spk]}">
#             <div class="line-meta">
#                 <span class="speaker-dot" style="background:{speaker_colors[spk]}"></span>
#                 <span class="speaker-name" style="color:{speaker_colors[spk]}">{escape_html(spk)}</span>
#                 <span class="time-range">{format_time(seg['start'])} – {format_time(seg['end'])}</span>
#                 {f'<span class="overlap-badge">🗣️ 重叠</span>' if is_overlap else ''}
#             </div>
#             <div class="line-text">{escape_html(seg['text'])}</div>
#         </div>
#         ''')

#     html = '<div class="transcript-container">' + ''.join(html_parts) + '</div>'

#     html += '''
#     <script>
#     (function() {
#         setTimeout(() => {
#             function seekTo(time) {
#                 const media = document.querySelector('video, audio');
#                 if (media) {
#                     media.currentTime = time;
#                     if (media.paused) media.play();
#                 }
#             }

#             const container = document.querySelector('.transcript-container');
#             if (container) {
#                 container.addEventListener('click', (e) => {
#                     const line = e.target.closest('.transcript-line');
#                     if (line && line.dataset.start) {
#                         const t = parseFloat(line.dataset.start);
#                         if (!isNaN(t)) seekTo(t);
#                     }
#                 });
#             }
#         }, 300);
#     })();
#     </script>
#     '''
#     return html


# # ─────────────────────────── 工具函数 ───────────────────────────

# # 🔧 新增：清理 JSONL item 的 key（strip 空格）
# def clean_item_keys(item: Dict) -> Dict:
#     """递归 strip 字典顶层 key 的前后空格"""
#     return {k.strip(): v for k, v in item.items()}


# # ─────────────────────────── Gradio 应用 ───────────────────────────

# # 🔧 全局 CSS，抽出来方便维护
# TRANSCRIPT_CSS = '''
# <style>
# .transcript-container {
#     font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
#     font-size: 14px;
#     line-height: 1.6;
#     color: #1f2937;
#     max-height: 500px;
#     overflow-y: auto;
#     padding: 8px 4px;
#     background: #fff;
#     border-radius: 8px;
#     border: 1px solid #e5e7eb;
# }
# .transcript-line {
#     padding: 10px 16px;
#     margin: 4px 8px;
#     border-radius: 8px;
#     border-left: 3px solid transparent;
#     cursor: pointer;
#     transition: all 0.15s ease;
#     background: #f9fafb;
#     color: #111827;
# }
# .transcript-line:hover {
#     background: #e5e7eb;
#     transform: translateX(2px);
# }
# .transcript-line.current {
#     background: #dcfce7 !important;
#     border-left-color: #22c55e !important;
#     box-shadow: 0 2px 8px rgba(34, 197, 94, 0.2);
# }
# .transcript-line.overlap {
#     background: #ffedd5 !important;
#     border-left-color: #fb923c !important;
# }
# .transcript-line.overlap.current {
#     background: linear-gradient(135deg, #dcfce7, #ffedd5) !important;
#     border-left-color: #22c55e !important;
# }
# .line-meta {
#     display: flex;
#     align-items: center;
#     gap: 8px;
#     font-size: 12px;
#     color: #6b7280;
#     margin-bottom: 4px;
#     flex-wrap: wrap;
# }
# .speaker-dot {
#     width: 8px;
#     height: 8px;
#     border-radius: 50%;
#     flex-shrink: 0;
# }
# .speaker-name {
#     font-weight: 600;
#     font-size: 13px;
# }
# .time-range {
#     opacity: 0.7;
#     font-family: monospace;
# }
# .overlap-badge {
#     background: #fed7aa;
#     color: #c2410c;
#     padding: 1px 8px;
#     border-radius: 99px;
#     font-size: 10px;
#     font-weight: 600;
# }
# .line-text {
#     font-size: 15px;
#     color: #1f2937;
#     line-height: 1.5;
# }
# .empty {
#     text-align: center;
#     color: #9ca3af;
#     padding: 40px;
#     font-size: 14px;
# }
# .parse-source {
#     text-align: right;
#     font-size: 11px;
#     color: #9ca3af;
#     padding: 4px 12px 0;
# }
# </style>
# '''


# def create_app(jsonl_path: str, default_idx: int = 0):
#     """创建 Gradio 应用"""

#     print(f"🔍 加载数据: {jsonl_path}")
#     data = []
#     if os.path.exists(jsonl_path):
#         with open(jsonl_path, 'r', encoding='utf-8') as f:
#             for i, line in enumerate(f):
#                 line = line.strip()
#                 if not line:
#                     continue
#                 try:
#                     item = json.loads(line)
#                     # 🔧 关键修复：strip 所有 key 的前后空格
#                     item = clean_item_keys(item)
#                     hyp_preview = item.get('hyp', '')[:80].replace('\n', '\\n')
#                     print(f"  ✅ [{i}] index={str(item.get('index', 'N/A'))[:40]}, hyp='{hyp_preview}...'")
#                     data.append(item)
#                 except json.JSONDecodeError as e:
#                     print(f"  ❌ [{i}] JSON解析失败: {e}")
#                     continue
#     else:
#         print(f"  ❌ 文件不存在: {jsonl_path}")

#     print(f"📊 共加载 {len(data)} 条有效数据")

#     if not data:
#         with gr.Blocks(title="🔍 调试模式") as demo:
#             gr.Markdown("## ❌ 未加载到数据")
#             gr.Textbox(f"检查路径: {jsonl_path}", label="错误信息", interactive=False)
#         return demo

#     # 🔧 预处理：智能提取转录段落
#     for idx, item in enumerate(data):
#         segments = extract_segments(item)
#         item['_segments'] = segments
#         item['_overlaps'] = detect_overlaps(segments)
#         # 记录解析来源，方便调试
#         if segments:
#             # 判断是从哪个字段解析出来的
#             source = '未知'
#             moss_text = item.get('moss_qwen_format_text', '')
#             hyp_text = item.get('hyp', '')
#             if moss_text and str(moss_text).strip().lower() not in ('none', 'null', ''):
#                 test = parse_hyp_content(str(moss_text))
#                 if test:
#                     source = 'moss_qwen_format_text'
#             if source == '未知' and hyp_text and str(hyp_text).strip().lower() not in ('none', 'null', ''):
#                 test = parse_hyp_content(str(hyp_text))
#                 if test:
#                     source = 'hyp'
#             if source == '未知':
#                 source = 'utterance'
#             item['_parse_source'] = source
#         else:
#             item['_parse_source'] = '无数据'
#         print(f"  📝 [{idx}] 解析 {len(segments)} 条语句 (来源: {item['_parse_source']})")

#     def get_media_path(item: Dict) -> Tuple[Optional[str], Optional[str]]:
#         """返回 (media_path, media_type: 'video'/'audio'/None)"""
#         # 🔧 依次尝试 video_path, wav_path
#         for key, mtype in [('video_path', 'video'), ('wav_path', 'audio')]:
#             path = item.get(key, '')
#             if path and isinstance(path, str) and os.path.exists(path):
#                 return path, mtype
#         return None, None

#     def update_display(idx: int, current_time: float = -1):
#         """更新显示内容"""
#         if idx < 0 or idx >= len(data):
#             return None, "<div class='empty'>请选择有效数据</div>", ""

#         item = data[idx]
#         segments = item['_segments']
#         overlaps = item['_overlaps']

#         media_path, media_type = get_media_path(item)

#         # 计算当前高亮的语句索引
#         highlight_idx = -1
#         if current_time >= 0 and segments:
#             for i, seg in enumerate(segments):
#                 if seg['start'] <= current_time < seg['end']:
#                     highlight_idx = i
#                     break

#         html = generate_transcript_html(segments, overlaps, current_time, highlight_idx)

#         # 🔧 添加解析来源提示
#         source_hint = f'<div class="parse-source">📌 解析来源: {item.get("_parse_source", "未知")} | 共 {len(segments)} 句</div>'

#         styled_html = TRANSCRIPT_CSS + source_hint + html

#         # 🔧 更丰富的 info 显示
#         index_str = str(item.get('index', 'N/A'))[:60]
#         duration = item.get('dialogue_duration', '?')
#         info_text = f"📋 {index_str} | ⏱ {duration}s"

#         return media_path, styled_html, info_text

#     # ─────────── 构建界面 ───────────
#     with gr.Blocks(title="🎬 转录可视化播放器", theme=gr.themes.Soft()) as demo:
#         gr.Markdown("## 🎬 语音转录同步播放器")
#         gr.Markdown("*🟢 绿色* = 当前播放语句 | *🟠 橙色* = 多人同时说话 | *点击语句可跳转播放位置*")

#         with gr.Row():
#             with gr.Column(scale=5, min_width=400):
#                 media_output = gr.Video(label="📹 视频/音频", interactive=False, height=400)
#                 time_slider = gr.Slider(label="播放进度", minimum=0, maximum=3600, step=0.01, visible=False)

#             with gr.Column(scale=7, min_width=500):
#                 transcript_html = gr.HTML(
#                     label="📝 转录内容",
#                     value="<div class='empty'>请选择数据项</div>",
#                     elem_id="transcript-box"
#                 )
#                 info_label = gr.Label(label="当前项", value="")

#         # 🔧 数据选择：显示更多上下文信息
#         indices = []
#         for i, d in enumerate(data):
#             idx_str = str(d.get('index', 'N/A'))[:45]
#             seg_count = len(d.get('_segments', []))
#             source = d.get('_parse_source', '?')
#             indices.append(f"{i}: {idx_str} [{seg_count}句/{source}]")

#         # 🔧 clamp default_idx
#         default_idx = max(0, min(default_idx, len(data) - 1))

#         index_dropdown = gr.Dropdown(
#             choices=indices,
#             value=indices[default_idx],
#             label="📁 选择数据项",
#             interactive=True
#         )

#         # 🔧 添加转录来源选择器（可手动切换）
#         source_radio = gr.Radio(
#             choices=["自动（推荐）", "moss_qwen_format_text", "hyp", "utterance"],
#             value="自动（推荐）",
#             label="📑 转录来源",
#             interactive=True
#         )

#         def on_source_change(selected_item: str, source_choice: str):
#             """切换转录来源时重新解析"""
#             if not selected_item:
#                 return "<div class='empty'>请选择数据项</div>"
#             idx = int(selected_item.split(':')[0])
#             if idx < 0 or idx >= len(data):
#                 return "<div class='empty'>无效索引</div>"

#             item = data[idx]

#             if source_choice == "自动（推荐）":
#                 segments = extract_segments(item)
#                 src = item.get('_parse_source', '自动')
#             elif source_choice == "moss_qwen_format_text":
#                 text = item.get('moss_qwen_format_text', '')
#                 segments = parse_hyp_content(str(text)) if text else []
#                 src = 'moss_qwen_format_text'
#             elif source_choice == "hyp":
#                 text = item.get('hyp', '')
#                 segments = parse_hyp_content(str(text)) if text else []
#                 src = 'hyp'
#             elif source_choice == "utterance":
#                 segments = parse_utterance_list(item.get('utterance', []))
#                 src = 'utterance'
#             else:
#                 segments = extract_segments(item)
#                 src = '自动'

#             overlaps = detect_overlaps(segments)
#             html = generate_transcript_html(segments, overlaps)
#             source_hint = f'<div class="parse-source">📌 解析来源: {src} | 共 {len(segments)} 句</div>'
#             return TRANSCRIPT_CSS + source_hint + html

#         source_radio.change(
#             fn=on_source_change,
#             inputs=[index_dropdown, source_radio],
#             outputs=[transcript_html]
#         )

#         # 事件绑定
#         def on_index_change(selected: str):
#             if not selected:
#                 return None, "<div class='empty'>请选择</div>", "", 0
#             idx = int(selected.split(':')[0])
#             media, html, info = update_display(idx)
#             return media, html, info, 0

#         index_dropdown.change(
#             fn=on_index_change,
#             inputs=[index_dropdown],
#             outputs=[media_output, transcript_html, info_label, time_slider]
#         )

#         # 初始化
#         demo.load(
#             fn=lambda: update_display(default_idx),
#             outputs=[media_output, transcript_html, info_label]
#         )

#         # JS 监听媒体时间更新（实现播放时同步高亮）
#         demo.load(js="""
#         () => {
#             let lastHighlight = -1;

#             function findCurrentIdx(time, lines) {
#                 for (let i = 0; i < lines.length; i++) {
#                     const start = parseFloat(lines[i].dataset.start);
#                     const end = parseFloat(lines[i].dataset.end || '9999');
#                     if (time >= start && time < end) return i;
#                 }
#                 // 🔧 fallback：找最近的已过去的语句
#                 let best = -1;
#                 for (let i = 0; i < lines.length; i++) {
#                     const start = parseFloat(lines[i].dataset.start);
#                     if (start <= time) best = i;
#                 }
#                 return best;
#             }

#             function updateHighlight(time) {
#                 const container = document.querySelector('.transcript-container');
#                 if (!container) return;
#                 const lines = container.querySelectorAll('.transcript-line');
#                 if (!lines.length) return;

#                 const idx = findCurrentIdx(time, lines);
#                 if (idx === lastHighlight) return;
#                 lastHighlight = idx;

#                 lines.forEach((el, i) => {
#                     el.classList.toggle('current', i === idx);
#                 });

#                 // 🔧 自动滚动到当前高亮行
#                 if (idx >= 0 && lines[idx]) {
#                     lines[idx].scrollIntoView({
#                         behavior: 'smooth',
#                         block: 'center'
#                     });
#                 }
#             }

#             const checkMedia = () => {
#                 const media = document.querySelector('video, audio');
#                 if (!media) return setTimeout(checkMedia, 500);

#                 media.addEventListener('timeupdate', () => {
#                     updateHighlight(media.currentTime);
#                 });

#                 // 🔧 seeked 事件也更新高亮
#                 media.addEventListener('seeked', () => {
#                     updateHighlight(media.currentTime);
#                 });
#             };
#             checkMedia();

#             // 🔧 MutationObserver：当媒体元素被替换时重新绑定
#             const observer = new MutationObserver(() => {
#                 lastHighlight = -1;
#                 checkMedia();
#             });
#             const appRoot = document.querySelector('gradio-app') || document.body;
#             observer.observe(appRoot, { childList: true, subtree: true });
#         }
#         """)

#     return demo


# # ─────────────────────────── 入口 ───────────────────────────

# if __name__ == "__main__":
#     import argparse

#     parser = argparse.ArgumentParser(description="语音转录可视化播放器（稳健版）")
#     parser.add_argument("--jsonl", type=str, default=None, help="JSONL 数据文件路径")
#     parser.add_argument("--port", type=int, default=7860, help="Gradio 服务端口")
#     parser.add_argument("--share", action="store_true", help="生成公开分享链接")
#     parser.add_argument("--index", type=int, default=0, help="默认加载的数据项索引")

#     args = parser.parse_args()

#     # 🔧 支持命令行指定路径，也保留默认路径
#     if args.jsonl:
#         jsonl_path = args.jsonl
#     else:
#         # 按优先级尝试多个默认路径
#         default_paths = [
#             "/mnt/data/yhdai/workspace/code/SoulX-Transcriber/demopage/assets/demo.jsonl",
#             # "/mnt/data/yhdai/workspace/code/SoulX-Transcriber/demopage/assets/drama.jsonl",
#             # "./demo.jsonl",
#         ]
#         jsonl_path = None
#         for p in default_paths:
#             if os.path.exists(p):
#                 jsonl_path = p
#                 break
#         if jsonl_path is None:
#             print("❌ 未找到 JSONL 文件，请通过 --jsonl 参数指定路径")
#             print(f"   尝试过的默认路径: {default_paths}")
#             exit(1)

#     if not os.path.exists(jsonl_path):
#         print(f"❌ 文件不存在: {jsonl_path}")
#         exit(1)

#     print(f"🚀 启动播放器: {jsonl_path}")
#     demo = create_app(jsonl_path, default_idx=args.index)

#     # 🔧 收集所有可能的媒体目录
#     allowed = list(set(filter(None, [
#         "/mnt",
#         "/tmp",
#         tempfile.gettempdir(),
#         os.path.dirname(os.path.abspath(jsonl_path)),
#     ])))

#     demo.launch(
#         server_port=args.port,
#         server_name="0.0.0.0",
#         share=args.share,
#         inbrowser=True,
#         allowed_paths=allowed
#     )





#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音转录可视化播放器（稳健版 v3）
功能：
1. 加载 JSONL 数据，解析带时间戳的转录结果
2. 左侧播放视频/音频，右侧同步高亮显示对应语句
3. 绿色高亮：当前播放时间对应的语句（纯前端 JS 驱动，实时跟随）
4. 橙色高亮：多人同时说话（时间重叠）的语句
5. 支持点击语句跳转播放位置
6. 自动检测多种转录格式（hyp / moss_qwen_format_text / utterance）
"""

import json
import re
import os
import gradio as gr
import tempfile

from typing import List, Dict, Optional, Tuple


# ═══════════════════════════ 数据解析 ═══════════════════════════

def parse_time_to_seconds(time_str: str) -> float:
    """
    解析时间字符串为秒数，支持：
    - "MM:SS.ss"    如 "00:01.49"
    - "SS.ss"       如 "1.49"
    - "HH:MM:SS.ss" 如 "01:02:03.50"
    """
    time_str = time_str.strip()
    if not time_str:
        return 0.0
    try:
        parts = time_str.split(':')
        if len(parts) == 1:
            return float(parts[0])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except (ValueError, AttributeError):
        pass
    return 0.0


def parse_hyp_line(line: str) -> Optional[Dict]:
    """
    解析单行转录：
    输入格式: [00:00.87 --> 00:01.49] Speaker 1: 现在
    """
    pattern = re.compile(
        r'\[(\d{2}:\d{2}\.\d{2})\s*-->\s*(\d{2}:\d{2}\.\d{2})\]\s*(Speaker \d+):\s*(.*)'
    )
    match = pattern.match(line.strip())
    if not match:
        return None
    start_str, end_str, speaker, text = match.groups()
    return {
        'start': parse_time_to_seconds(start_str),
        'end': parse_time_to_seconds(end_str),
        'speaker': speaker.strip(),
        'text': text.strip(),
    }


def parse_hyp_content(hyp: str) -> List[Dict]:
    """解析完整的 hyp 字符串"""
    if not hyp or hyp.strip().lower() in ('none', 'null', ''):
        return []
    segments = []
    for line in hyp.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        seg = parse_hyp_line(line)
        if seg:
            segments.append(seg)
    segments.sort(key=lambda x: x['start'])
    return segments


def parse_utterance_list(utterances: list) -> List[Dict]:
    """从 utterance 字段（list of dict）解析，作为 fallback"""
    if not utterances or not isinstance(utterances, list):
        return []
    spk_map = {}
    segments = []
    for utt in utterances:
        if not isinstance(utt, dict):
            continue
        try:
            spk_id = utt.get('spk_id', 'unknown')
            if spk_id not in spk_map:
                spk_map[spk_id] = f"Speaker {len(spk_map) + 1}"
            seg = {
                'start': float(utt.get('start', 0)),
                'end': float(utt.get('end', 0)),
                'speaker': spk_map[spk_id],
                'text': str(utt.get('text', '')).strip(),
            }
            if seg['text']:
                segments.append(seg)
        except (ValueError, TypeError):
            continue
    segments.sort(key=lambda x: x['start'])
    return segments


def extract_segments(item: Dict) -> Tuple[List[Dict], str]:
    """
    按优先级尝试解析转录内容，返回 (segments, source_name)
    优先级: moss_qwen_format_text > hyp > utterance
    """
    for key in ('moss_qwen_format_text', 'hyp'):
        text = item.get(key, '')
        if text and str(text).strip().lower() not in ('none', 'null', ''):
            segs = parse_hyp_content(str(text))
            if segs:
                return segs, key

    utt_list = item.get('utterance', [])
    if utt_list:
        segs = parse_utterance_list(utt_list)
        if segs:
            return segs, 'utterance'

    return [], '无数据'


def detect_overlaps(segments: List[Dict], tolerance: float = 0.1) -> List[bool]:
    """检测每个语句是否与其他语句时间重叠"""
    overlaps = [False] * len(segments)
    for i, seg_i in enumerate(segments):
        for j, seg_j in enumerate(segments):
            if i == j:
                continue
            if seg_i['start'] < seg_j['end'] - tolerance and seg_i['end'] > seg_j['start'] + tolerance:
                overlaps[i] = True
                break
    return overlaps


# ═══════════════════════════ HTML 生成 ═══════════════════════════

def fmt_time(seconds: float) -> str:
    m, s = int(seconds // 60), int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def esc(text: str) -> str:
    return (text.replace('&', '&amp;').replace('<', '&lt;')
               .replace('>', '&gt;').replace('"', '&quot;'))


# 🔧 全局 CSS
CSS = '''
<style>
.transcript-container {
    font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    font-size: 14px; line-height: 1.6; color: #1f2937;
    max-height: 520px; overflow-y: auto;
    padding: 8px 4px; background: #fff;
    border-radius: 8px; border: 1px solid #e5e7eb;
    scroll-behavior: smooth;
}
.transcript-line {
    padding: 10px 16px; margin: 4px 8px;
    border-radius: 8px; border-left: 3px solid transparent;
    cursor: pointer; transition: background 0.15s, border-color 0.15s;
    background: #f9fafb; color: #111827;
}
.transcript-line:hover { background: #e5e7eb; }
.transcript-line.active {
    background: #dcfce7 !important;
    border-left-color: #22c55e !important;
    box-shadow: 0 2px 8px rgba(34,197,94,0.18);
}
.transcript-line.overlap {
    background: #ffedd5 !important;
    border-left-color: #fb923c !important;
}
.transcript-line.overlap.active {
    background: linear-gradient(135deg, #dcfce7, #ffedd5) !important;
    border-left-color: #22c55e !important;
}
.line-meta {
    display: flex; align-items: center; gap: 8px;
    font-size: 12px; color: #6b7280; margin-bottom: 4px; flex-wrap: wrap;
}
.speaker-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.speaker-name { font-weight: 600; font-size: 13px; }
.time-range { opacity: 0.7; font-family: monospace; font-size: 11px; }
.overlap-badge {
    background: #fed7aa; color: #c2410c;
    padding: 1px 8px; border-radius: 99px; font-size: 10px; font-weight: 600;
}
.line-text { font-size: 15px; color: #1f2937; line-height: 1.5; }
.empty { text-align: center; color: #9ca3af; padding: 40px; font-size: 14px; }
.parse-info {
    text-align: right; font-size: 11px; color: #9ca3af;
    padding: 4px 12px 2px;
}
</style>
'''


def build_transcript_html(segments: List[Dict], overlaps: List[bool], source: str) -> str:
    """生成完整的转录 HTML（含 CSS + JS）"""

    if not segments:
        return CSS + '<div class="empty">⚠️ 未解析到转录内容</div>'

    # 说话人颜色
    palette = ['#4fc3f7', '#81c784', '#ffb74d', '#ba68c8', '#e57373',
               '#64b5f6', '#f06292', '#aed581', '#ffcc80', '#90caf9']
    spk_colors = {}
    parts = []

    for idx, seg in enumerate(segments):
        spk = seg['speaker']
        if spk not in spk_colors:
            spk_colors[spk] = palette[len(spk_colors) % len(palette)]
        color = spk_colors[spk]
        is_overlap = overlaps[idx] if idx < len(overlaps) else False
        cls = 'transcript-line' + (' overlap' if is_overlap else '')

        # 🔧 data-start / data-end 用于 JS 实时匹配
        parts.append(f'''
        <div class="{cls}" data-idx="{idx}" data-start="{seg['start']:.3f}" data-end="{seg['end']:.3f}">
            <div class="line-meta">
                <span class="speaker-dot" style="background:{color}"></span>
                <span class="speaker-name" style="color:{color}">{esc(spk)}</span>
                <span class="time-range">{fmt_time(seg['start'])} – {fmt_time(seg['end'])}</span>
                {'<span class="overlap-badge">🗣️ 重叠</span>' if is_overlap else ''}
            </div>
            <div class="line-text">{esc(seg['text'])}</div>
        </div>''')

    info = f'<div class="parse-info">📌 来源: {esc(source)} | 共 {len(segments)} 句</div>'
    container = '<div class="transcript-container" id="tc">' + ''.join(parts) + '</div>'

    # ═══════════ 🔧 核心 JS：纯前端实时高亮 + 自动滚动 + 点击跳转 ═══════════
    js = r'''
    <script>
    (function(){
        // 防止重复绑定
        if (window.__tcBound) return;
        window.__tcBound = true;

        let lastActiveIdx = -1;
        let userScrolling = false;
        let scrollTimer = null;

        // ── 实时高亮 ──
        function highlightAtTime(t) {
            const container = document.getElementById('tc');
            if (!container) return;
            const lines = container.querySelectorAll('.transcript-line');
            if (!lines.length) return;

            let activeIdx = -1;
            // 精确匹配：当前时间落在 [start, end) 内
            for (let i = 0; i < lines.length; i++) {
                const s = parseFloat(lines[i].dataset.start);
                const e = parseFloat(lines[i].dataset.end);
                if (t >= s && t < e) { activeIdx = i; break; }
            }
            // 🔧 Fallback：没有精确命中时，找最近的「已经开始但还没到下一句」的行
            if (activeIdx === -1) {
                for (let i = lines.length - 1; i >= 0; i--) {
                    if (t >= parseFloat(lines[i].dataset.start)) { activeIdx = i; break; }
                }
            }

            if (activeIdx === lastActiveIdx) return;
            lastActiveIdx = activeIdx;

            // 更新 class
            lines.forEach((el, i) => {
                if (i === activeIdx) el.classList.add('active');
                else el.classList.remove('active');
            });

            // 🔧 自动滚动（用户手动滚动时暂停 2 秒）
            if (activeIdx >= 0 && !userScrolling) {
                lines[activeIdx].scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }

        // ── 检测用户手动滚动，暂停自动滚动 ──
        function onContainerScroll() {
            userScrolling = true;
            clearTimeout(scrollTimer);
            scrollTimer = setTimeout(() => { userScrolling = false; }, 2000);
        }

        // ── 点击跳转 ──
        function onLineClick(e) {
            const line = e.target.closest('.transcript-line');
            if (!line) return;
            const t = parseFloat(line.dataset.start);
            if (isNaN(t)) return;
            const media = document.querySelector('video, audio');
            if (media) {
                media.currentTime = t;
                if (media.paused) media.play();
            }
        }

        // ── 绑定媒体事件 ──
        function bindMedia() {
            const media = document.querySelector('video, audio');
            if (!media) return setTimeout(bindMedia, 300);

            // 🔧 用 requestAnimationFrame 轮询代替 timeupdate（更流畅）
            let rafId = null;
            function tick() {
                if (!media.paused) highlightAtTime(media.currentTime);
                rafId = requestAnimationFrame(tick);
            }

            media.addEventListener('play', () => {
                if (!rafId) tick();
            });
            media.addEventListener('pause', () => {
                cancelAnimationFrame(rafId);
                rafId = null;
                highlightAtTime(media.currentTime);
            });
            media.addEventListener('seeked', () => {
                highlightAtTime(media.currentTime);
            });

            // 初始状态
            highlightAtTime(media.currentTime);
            if (!media.paused) tick();
        }

        // ── 绑定容器事件 ──
        function bindContainer() {
            const container = document.getElementById('tc');
            if (!container) return setTimeout(bindContainer, 300);
            container.addEventListener('click', onLineClick);
            container.addEventListener('scroll', onContainerScroll, { passive: true });
        }

        bindMedia();
        bindContainer();

        // 🔧 MutationObserver：切换数据项后重新绑定
        const obs = new MutationObserver(() => {
            lastActiveIdx = -1;
            window.__tcBound = false;
            setTimeout(() => {
                window.__tcBound = true;
                bindMedia();
                bindContainer();
            }, 200);
        });
        const root = document.querySelector('.gradio-container') || document.body;
        obs.observe(root, { childList: true, subtree: true });
    })();
    </script>
    '''

    return CSS + info + container + js


# ═══════════════════════════ 工具函数 ═══════════════════════════

def clean_keys(item: Dict) -> Dict:
    """strip 字典 key 的前后空格"""
    return {k.strip(): v for k, v in item.items()}


# ═══════════════════════════ Gradio 应用 ═══════════════════════════

def create_app(jsonl_path: str, default_idx: int = 0):

    print(f"🔍 加载数据: {jsonl_path}")
    data = []
    if os.path.exists(jsonl_path):
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    item = clean_keys(item)  # 🔧 strip key 空格
                    data.append(item)
                    print(f"  ✅ [{i}] {str(item.get('index','?'))[:40]}")
                except json.JSONDecodeError as e:
                    print(f"  ❌ [{i}] JSON 解析失败: {e}")
    else:
        print(f"  ❌ 文件不存在: {jsonl_path}")

    print(f"📊 共加载 {len(data)} 条数据")

    if not data:
        with gr.Blocks(title="调试") as demo:
            gr.Markdown(f"## ❌ 未加载到数据\n路径: `{jsonl_path}`")
        return demo

    # 预处理
    for idx, item in enumerate(data):
        segs, src = extract_segments(item)
        item['_segments'] = segs
        item['_overlaps'] = detect_overlaps(segs)
        item['_source'] = src
        print(f"  📝 [{idx}] {len(segs)} 句 (来源: {src})")

    def get_media(item):
        for key, mtype in [('video_path', 'video'), ('wav_path', 'audio')]:
            p = item.get(key, '')
            if p and isinstance(p, str) and os.path.exists(p):
                return p, mtype
        return None, None

    def show(idx: int):
        if idx < 0 or idx >= len(data):
            return None, '<div class="empty">请选择有效数据</div>', ""
        item = data[idx]
        media_path, _ = get_media(item)
        html = build_transcript_html(item['_segments'], item['_overlaps'], item['_source'])
        info = f"📋 {str(item.get('index','?'))[:55]} | ⏱ {item.get('dialogue_duration','?')}s"
        return media_path, html, info

    # ─── 界面 ───
    default_idx = max(0, min(default_idx, len(data) - 1))

    with gr.Blocks(title="🎬 转录可视化播放器", theme=gr.themes.Soft()) as demo:
        gr.Markdown("## 🎬 语音转录同步播放器")
        gr.Markdown("🟢 绿色 = 当前播放语句 &nbsp;|&nbsp; 🟠 橙色 = 多人同时说话 &nbsp;|&nbsp; 点击语句可跳转")

        with gr.Row():
            with gr.Column(scale=5, min_width=400):
                media_out = gr.Video(label="📹 视频/音频", interactive=False, height=400)

            with gr.Column(scale=7, min_width=500):
                html_out = gr.HTML(value="<div class='empty'>请选择数据项</div>", elem_id="transcript-box")
                info_out = gr.Label(label="当前项", value="")

        # 选择器：显示句数和来源
        choices = []
        for i, d in enumerate(data):
            tag = str(d.get('index', '?'))[:42]
            n = len(d.get('_segments', []))
            choices.append(f"{i}: {tag} [{n}句]")

        dropdown = gr.Dropdown(
            choices=choices,
            value=choices[default_idx],
            label="📁 选择数据项",
            interactive=True
        )

        # 🔧 手动切换来源
        source_radio = gr.Radio(
            choices=["自动", "moss_qwen_format_text", "hyp", "utterance"],
            value="自动", label="📑 转录来源", interactive=True
        )

        def on_dropdown(selected):
            if not selected:
                return None, '<div class="empty">请选择</div>', ""
            idx = int(selected.split(':')[0])
            return show(idx)

        dropdown.change(fn=on_dropdown, inputs=[dropdown], outputs=[media_out, html_out, info_out])

        def on_source(selected_item, src):
            if not selected_item:
                return '<div class="empty">请选择数据项</div>'
            idx = int(selected_item.split(':')[0])
            if idx < 0 or idx >= len(data):
                return '<div class="empty">无效</div>'
            item = data[idx]

            if src == "自动":
                segs, sname = extract_segments(item)
            elif src == "utterance":
                segs = parse_utterance_list(item.get('utterance', []))
                sname = 'utterance'
            else:
                segs = parse_hyp_content(str(item.get(src, '')))
                sname = src

            overlaps = detect_overlaps(segs)
            return build_transcript_html(segs, overlaps, sname)

        source_radio.change(fn=on_source, inputs=[dropdown, source_radio], outputs=[html_out])

        # 初始加载
        demo.load(fn=lambda: show(default_idx), outputs=[media_out, html_out, info_out])

    return demo


# ═══════════════════════════ 入口 ═══════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="语音转录可视化播放器（稳健版 v3）")
    parser.add_argument("--jsonl", type=str, default=None, help="JSONL 文件路径")
    parser.add_argument("--port", type=int, default=7860, help="端口")
    parser.add_argument("--share", action="store_true", help="公开分享")
    parser.add_argument("--index", type=int, default=0, help="默认数据项索引")
    args = parser.parse_args()

    if args.jsonl:
        jsonl_path = args.jsonl
    else:
        candidates = [
            "/mnt/data/yhdai/workspace/code/SoulX-Transcriber/demopage/assets/demo.jsonl",
            "/mnt/data/yhdai/workspace/code/SoulX-Transcriber/demopage/assets/drama.jsonl",
            "./demo.jsonl",
        ]
        jsonl_path = next((p for p in candidates if os.path.exists(p)), None)
        if not jsonl_path:
            print(f"❌ 未找到 JSONL，请用 --jsonl 指定。尝试过: {candidates}")
            exit(1)

    if not os.path.exists(jsonl_path):
        print(f"❌ 文件不存在: {jsonl_path}")
        exit(1)

    print(f"🚀 启动: {jsonl_path}")
    demo = create_app(jsonl_path, default_idx=args.index)

    allowed = list(set(filter(None, [
        "/mnt", "/tmp", tempfile.gettempdir(),
        os.path.dirname(os.path.abspath(jsonl_path)),
    ])))

    demo.launch(
        server_port=args.port, server_name="0.0.0.0",
        share=args.share, inbrowser=True, allowed_paths=allowed
    )
