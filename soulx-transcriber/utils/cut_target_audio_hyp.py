import re
import json
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional

from pydub import AudioSegment  # pip install pydub
# 注意：pydub 需要 ffmpeg/ffprobe 支持


# ---------- 时间 & hyp 解析工具 ----------

TIME_RE = re.compile(r"(\d{2}):(\d{2}\.\d{2})")
LINE_RE = re.compile(
    r"\[(\d{2}:\d{2}\.\d{2})\s*-->\s*(\d{2}:\d{2}\.\d{2})\]\s*(Speaker\s+\d+):\s*(.*)"
)


def ts_to_sec(ts: str) -> float:
  """'MM:SS.xx' -> seconds (float)."""
  m, s = ts.split(":")
  return int(m) * 60 + float(s)


def sec_to_ts(t: float) -> str:
  """seconds (float) -> 'MM:SS.xx'."""
  if t < 0:
    t = 0.0
  m = int(t // 60)
  s = t - m * 60
  return f"{m:02d}:{s:05.2f}"


@dataclass
class UtterLine:
  start: float
  end: float
  speaker: str
  text: str


def parse_hyp(hyp: str) -> List[UtterLine]:
  """解析 hyp 字符串为结构化列表。"""
  lines = []
  if not hyp:
    return lines
  for raw in hyp.strip().splitlines():
    raw = raw.strip()
    if not raw:
      continue
    m = LINE_RE.match(raw)
    if not m:
      continue
    start_ts, end_ts, spk, text = m.groups()
    lines.append(
      UtterLine(
        start=ts_to_sec(start_ts),
        end=ts_to_sec(end_ts),
        speaker=spk.strip(),
        text=text.strip(),
      )
    )
  return lines


def format_hyp(lines: List[UtterLine]) -> str:
  """将结构化结果重新格式化为 hyp 字符串。"""
  out = []
  for l in lines:
    s = sec_to_ts(l.start)
    e = sec_to_ts(l.end)
    out.append(f"[{s} --> {e}] {l.speaker}: {l.text}")
  return "\n".join(out) + ("\n" if out else "")


# ---------- 核心函数：裁剪音频 + 偏移时间戳 ----------

def slice_dialogue_item(
    item: Dict[str, Any],
    out_audio_path: str,
    start_s: float,
    end_s: float,
) -> Tuple[Dict[str, Any], Optional[str]]:
  """
  输入一条数据（包含 'wav_path' 和 'hyp'），
  按 [start_s, end_s] 裁剪音频，并导出对应范围内的识别结果（带偏移时间）。
  
  返回:
    new_item: 更新后的 dict（hyp 时间戳已偏移，wav_path 指向新文件）
    out_audio_path: 新音频路径（如果裁剪失败则为 None）
  """
  wav_path = item.get("wav_path")
  hyp = item.get("hyp", "")
  if wav_path is None:
    raise ValueError("item 中缺少 'wav_path' 字段")

  if end_s <= start_s:
    raise ValueError("end_s 必须大于 start_s")

  # 1. 裁剪音频
  try:
    audio = AudioSegment.from_file(wav_path)
  except Exception as e:
    print(f"加载音频失败: {e}")
    return item, None

  full_ms = len(audio)
  start_ms = int(max(start_s, 0) * 1000)
  end_ms = int(min(end_s, full_ms / 1000.0) * 1000)
  if end_ms <= start_ms:
    # 裁剪区间在音频外，返回原始
    return item, None

  sliced = audio[start_ms:end_ms]
  sliced.export(out_audio_path, format=out_audio_path.split(".")[-1])

  # 2. 解析 hyp，筛选重叠片段，并对时间戳做偏移
  lines = parse_hyp(hyp)
  new_lines: List[UtterLine] = []

  for l in lines:
    # 原始区间 [l.start, l.end] 与 [start_s, end_s] 是否存在重叠
    if l.end <= start_s or l.start >= end_s:
      continue  # 无重叠，跳过

    # 裁剪后的新时间 = 原时间 - start_s，并裁剪到 [0, end_s-start_s]
    new_start = max(l.start, start_s) - start_s
    new_end = min(l.end, end_s) - start_s

    if new_end <= new_start:
      continue

    new_lines.append(
      UtterLine(
        start=new_start,
        end=new_end,
        speaker=l.speaker,
        text=l.text,
      )
    )

  # 3. 重新格式化 hyp，并构造新的 item
  new_hyp = format_hyp(new_lines)

  new_item = dict(item)  # 浅拷贝
  new_item["hyp"] = new_hyp
  new_item["wav_path"] = out_audio_path
  new_item["slice_start_s"] = float(start_s)
  new_item["slice_end_s"] = float(end_s)

  return new_item, out_audio_path


# ---------- 使用示例 ----------

if __name__ == "__main__":
  # 假定你从 JSONL / API 得到一条数据（和你问题中的结构类似）
  item = {"index": "R8002_M8002_01005410_01327040", "wav_path": "/mnt/data/MIGDATA/AU/opensource_sd/Alimeeting/processed_5min/Test_Ali_far/wav_segment_dir/R8002_M8002_01005410_01327040.wav", "hyp": "[00:00.98 --> 00:01.47] Speaker 1: 嗯\n[00:01.45 --> 00:04.97] Speaker 2: 有这个获奖的同时有这个成就感\n[00:05.08 --> 00:07.30] Speaker 3: 对然后他们也来个感言\n[00:07.48 --> 00:08.07] Speaker 2: 啊\n[00:08.17 --> 00:19.41] Speaker 1: 一般都是端杯酒上去对哦那那那咱们既然说到奖了咱们说一下奖品吧就最大的奖大概就是就是分几个几个类型的奖\n[00:19.55 --> 00:24.06] Speaker 3: 不是准备是怎么弄这是直接是给钱的还是实物的\n[00:24.13 --> 00:26.02] Speaker 2: 我感觉钱要\n[00:26.49 --> 00:27.84] Speaker 1: 可以一等奖是钱\n[00:27.51 --> 00:36.03] Speaker 4: 看你的预算呀你要一百块钱的奖品你就是给奖品别给钱你也给不出手如果是五千块钱的就可以给钱就不用给奖品了\n[00:36.52 --> 00:37.21] Speaker 1: 嗯\n[00:37.45 --> 00:39.98] Speaker 2: 咱们总算预算是十万是吗\n[00:40.00 --> 00:40.41] Speaker 1: 对\n[00:40.69 --> 00:43.73] Speaker 2: 那一等奖不是不是一等奖直接\n[00:42.85 --> 00:47.08] Speaker 1: 还包括场地啊就是就是吃喝呀这些东西对\n[00:45.68 --> 00:48.35] Speaker 2: 我算了算应该还够一万块钱差不多\n[00:48.60 --> 00:53.91] Speaker 3: 不你这个这所谓的这一二三等奖这是抽奖的形式来的是不是\n[00:53.97 --> 00:54.39] Speaker 1: 对\n[00:54.57 --> 00:56.94] Speaker 3: 但是他有一些固定的奖是要发的\n[00:56.13 --> 00:57.90] Speaker 2: 年终奖年终奖那是\n[00:57.02 --> 00:59.39] Speaker 1: 优秀优秀员工奖啊什么的\n[00:58.36 --> 01:02.98] Speaker 3: 这个这个东西不放在这里头不不在这个预算里面\n[01:00.39 --> 01:01.89] Speaker 2: 年终奖不在这个十万里\n[01:02.60 --> 01:12.54] Speaker 1: 不是年终奖是绩效超额奖比方说今年完成在今年完成了百分之百的那个员工可能就这一个人他的绩效超了五十万那你是不是要单独给他发个奖\n[01:04.79 --> 01:06.97] Speaker 3: 对对对优秀员工的绩效的\n[01:12.62 --> 01:17.33] Speaker 3: 但是这个不在这个预算里面儿但颁奖在这个颁奖在这个程序里面\n[01:14.33 --> 01:15.61] Speaker 2: 啊不在这十万里边儿\n[01:15.98 --> 01:22.12] Speaker 4: 不过不过这个是应该在预算里的因为这个只要是在年会里呢奖金就全都是在一起的\n[01:22.52 --> 01:22.97] Speaker 1: 嗯\n[01:23.39 --> 01:24.31] Speaker 2: 那这十万不够\n[01:24.56 --> 01:25.67] Speaker 3: 对奖他五万\n[01:25.78 --> 01:27.43] Speaker 2: 啊那十万绝对不够\n[01:27.69 --> 01:32.08] Speaker 1: 不用奖那么多呀因为你这个可能会有很多人呀嗯\n[01:32.25 --> 01:34.02] Speaker 3: 那得弄出一个比例出来\n[01:34.10 --> 01:37.22] Speaker 1: 咱们先说说都都都有什么奖吧都有什么奖\n[01:36.83 --> 01:40.00] Speaker 3: 要不就是现金那你看iphone现在流行\n[01:40.22 --> 01:41.83] Speaker 1: 嗯咱们讨论一下先\n[01:40.94 --> 01:41.83] Speaker 3: 指得着吗\n[01:40.96 --> 01:50.68] Speaker 2: 奖手机奖手机太俗了因为现在咱们这个几乎人手都都有家里或者是好几部一人手这个奖手机就有点像\n[01:50.25 --> 01:51.41] Speaker 4: 但是这个是最实用的\n[01:51.58 --> 01:54.68] Speaker 1: 就是这个这个就是价值看起来也是比较高的\n[01:54.46 --> 01:55.03] Speaker 2: 是实用\n[01:55.06 --> 01:55.41] Speaker 3: 对\n[01:55.58 --> 01:57.89] Speaker 2: 有有必要就是新鲜的电子产品\n[01:58.48 --> 02:03.68] Speaker 1: 哦无人机但是接受度比较高哎有可能他不需要啊但是手机是每个人都需要\n[01:58.60 --> 02:00.90] Speaker 3: 那比如说无人机什么\n[02:02.28 --> 02:02.66] Speaker 4: 对呀\n[02:04.16 --> 02:05.60] Speaker 2: 他自己不用可以送给家人\n[02:05.84 --> 02:07.62] Speaker 1: 对呀而且他也可以卖呀\n[02:08.71 --> 02:10.66] Speaker 2: 啊这个这个行这个行\n[02:10.69 --> 02:13.62] Speaker 1: 手机ipad我觉得很多公司都是都会有的\n[02:13.95 --> 02:14.28] Speaker 4: 不是说\n[02:14.15 --> 02:16.92] Speaker 2: 咱们为什么不送华为呢为什么要送ipad呢\n[02:16.72 --> 02:20.98] Speaker 3: 我只是举个例子嘛电子产品手机\n[02:17.29 --> 02:19.91] Speaker 1: 咱们现在在讨论咱们现在在讨论\n[02:21.95 --> 02:25.39] Speaker 1: 呃那个大家先说一下就是有什么奖品比较合适吧\n[02:26.51 --> 02:33.12] Speaker 4: 就是就是电子家电类的产品大家都能用得上的这种对大家都说一说\n[02:30.29 --> 02:31.93] Speaker 1: 家电比如说比如说啥\n[02:33.73 --> 02:39.67] Speaker 4: 就是那个比如像那个戴森的吹风机吸尘器就是这些呃现在在打折呢我看价格还挺便宜的\n[02:39.69 --> 02:42.42] Speaker 2: 这些都是针对男男男男同事的\n[02:43.08 --> 02:46.26] Speaker 3: 吹风机女性是一定要的啊啊啊\n[02:43.10 --> 02:46.25] Speaker 2: 啊女女啊不是啊女同事我说的是女同事\n[02:45.48 --> 02:46.92] Speaker 1: 对对对电子产品呀\n[02:46.87 --> 02:49.66] Speaker 2: 你得考也得把男同事考虑进来\n[02:49.39 --> 02:50.23] Speaker 3: 剃须刀啊\n[02:50.59 --> 02:51.92] Speaker 2: 啊行啊可以啊\n[02:51.90 --> 02:58.54] Speaker 1: 嗯可以啊就是那很多人很多人都有家属嘛可以送给自己老公啊男朋友什么的是吧还有自己父亲是吧\n[02:57.19 --> 02:57.88] Speaker 2: 啊对对对\n[02:58.59 --> 03:02.30] Speaker 4: 就是日常用得上的就行然后分出价值档次来就可以\n[02:59.91 --> 03:00.24] Speaker 1: 嗯\n[03:01.90 --> 03:12.05] Speaker 3: 对然后就比如说最后没有抽到前几等奖的设几个就一对对对有个阳光普照奖比如就设一二三等奖还是一二三四五怎样设个几等\n[03:06.06 --> 03:06.87] Speaker 1: 阳光普照\n[03:10.15 --> 03:10.50] Speaker 1: 嗯\n[03:11.12 --> 03:14.79] Speaker 4: 最后最后必须得有倒数选一个嗯\n[03:11.14 --> 03:11.44] Speaker 2: 一二三\n[03:14.72 --> 03:15.35] Speaker 2: 啊\n[03:15.00 --> 03:15.36] Speaker 3: 对\n[03:15.28 --> 03:16.20] Speaker 1: 咱们还是多嘛\n[03:15.76 --> 03:21.03] Speaker 3: 然后还有万一没用万一没有到场的你也给人一个福利奖\n[03:17.62 --> 03:17.88] Speaker 2: 来\n[03:20.41 --> 03:21.00] Speaker 1: 嗯\n[03:20.50 --> 03:22.52] Speaker 2: 啊嗯来个小高潮\n[03:21.27 --> 03:27.75] Speaker 1: 因为奖大概就就是就是就是可能说的还是这么多但是咱们先得确定一下都有什么奖是吧\n[03:27.84 --> 03:28.21] Speaker 3: 嗯\n[03:28.21 --> 03:40.43] Speaker 1: 呃一二三等奖呃是是抽奖的然后其他的呢那个是福利奖福利奖就是未抽到未抽到那个就是奖的一些同事就是那个安慰一下安慰奖\n[03:31.79 --> 03:32.16] Speaker 3: 嗯\n[03:38.70 --> 03:52.64] Speaker 4: 比如说就五十个奖因为本来就五十个人所以大家都有然后呢可能就是阳就是最低档的四等奖是最多的一共有十五个然后再三等奖可能就是七八个然后再往上一层一层叠一等奖就是一个\n[03:42.72 --> 03:43.12] Speaker 3: 对\n[03:52.84 --> 03:57.36] Speaker 4: 就是越来越少但是大家都有奖小奖都特别小小奖可能就是说的什么\n[03:57.36 --> 03:57.89] Speaker 2: 水杯\n[03:57.92 --> 04:03.57] Speaker 4: 啊一个就剃须刀之类的也不贵然后那个一个很普通的几十块钱的东西就完了\n[04:03.57 --> 04:10.84] Speaker 1: 嗯那是不那那个呃觉得就是像什么京东卡呀什么购物卡之类的那个合不合适啊\n[04:11.19 --> 04:15.43] Speaker 3: 这是一般都是平时那个年节呀什么那些发的那个福利\n[04:15.62 --> 04:18.06] Speaker 1: 嗯那就是还是实物奖是吧\n[04:16.35 --> 04:16.84] Speaker 4: 可以\n[04:18.49 --> 04:27.88] Speaker 2: 不是他那个他那个烘托不出这个年会的气氛来你卡太小就一张卡你哪怕是十块钱的一个杯子呢大家看不见\n[04:18.50 --> 04:20.43] Speaker 3: 但是你是说比如说去年\n[04:26.40 --> 04:27.62] Speaker 1: 因为就是女同事\n[04:28.00 --> 04:33.61] Speaker 1: 因为女同事比较多女同事就是逛商场什么的可能会我觉得还是女同事还是比较比较需要的\n[04:33.65 --> 04:46.54] Speaker 4: 但是就是你要统一一下比如你要抽卡就全都抽卡要抽实物的奖励就全都实物因为有的时候我们原来是你是最低等奖是一个京东卡然后上面是实物结果大家其实都想要那个卡\n[04:39.06 --> 04:39.43] Speaker 2: 对\n[04:46.80 --> 04:49.71] Speaker 4: 就是两个是两个档是完全不同的东西\n[04:47.85 --> 04:48.58] Speaker 1: 啊\n[04:49.98 --> 04:52.00] Speaker 2: 一个看得见的东西一个看不见的东西\n[04:52.11 --> 04:55.64] Speaker 4: 就是大家都要去换京东卡说我拿我的三等奖给你换京东卡去\n[04:57.21 --> 05:00.77] Speaker 1: 嗯那就还是都是实物\n[05:00.77 --> 05:05.34] Speaker 4: 对都是东西大家就不用抢啊就是谁谁抽着什么就什么对\n[05:05.60 --> 05:05.91] Speaker 2: 嗯\n[05:05.91 --> 05:06.34] Speaker 1: 嗯\n[05:06.43 --> 05:12.05] Speaker 2: 然后你说的那个就是最后必就是哄哄领导发现金最带劲了\n[05:07.44 --> 05:07.82] Speaker 3: 那\n[05:10.88 --> 05:11.28] Speaker 3: 嗯\n[05:12.43 --> 05:17.04] Speaker 4: 对呀这个是最有气氛的一般领导都会准备好领导要来了就会准备好这东西\n[05:13.69 --> 05:13.98] Speaker 2: 啊\n[05:16.45 --> 05:16.75] Speaker 2: 对\n[05:17.38 --> 05:17.74] Speaker 2: 嗯\n[05:17.46 --> 05:21.40] Speaker 1: 哦那就是那个就是帮领导准备一下那个现金红包\n"}


  # 例如：想要导出 [10s, 40s] 这一段
  new_item, new_wav = slice_dialogue_item(
    item=item,
    out_audio_path="/mnt/data/yhdai/workspace/code/SoulX-Transcriber/Soul-AILab.github.io/soulx-transcriber/assets/meeting.wav",
    start_s=40.0,
    end_s=82.12,
  )

  print("新音频路径:", new_wav)
  print("新 hyp:\n", new_item["hyp"])
  # 你也可以把 new_item 写回 JSONL
  # print(json.dumps(new_item, ensure_ascii=False))
