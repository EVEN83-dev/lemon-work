# -*- coding: utf-8 -*-
"""
小而精路线：Agent 数字角色系统 — 表情系统 + 每日随机行为
=============================================================
小而精差异化功能 - 让 Lemon Code 有"人格"。

功能：
1. 表情系统：10种表情（微笑/生气/思考/困倦/惊讶/开心/疑惑/无聊/专注/害羞）
2. 每日随机行为：扔垃圾、装睡、发呆、打哈欠、伸懒腰、看时间、喝奶茶、看文档、记笔记
3. 点击交互：单击微笑、连续点击生气
4. 道具系统：奶茶杯、文档、笔记本、垃圾桶、眼罩
5. 当前状态广播到前端：表情 + 行为 + 道具

设计原则：
- 与用户 memory 中的"数码机器人表情"需求一致
- 眼睛使用垂直椭圆形（9×14px），间距 18px
- 无瞳孔，用眼形变化表达情绪
- 矩形身体，小眼睛
"""

import random
import time
import threading
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum


# ============================================================
# 表情系统
# ============================================================

class Emotion(Enum):
    """表情枚举"""
    SMILE = "smile"           # 微笑 → 眼睛弯弯 (^_^)
    ANGRY = "angry"           # 生气 → 眼睛变细 (>_<)
    THINKING = "thinking"     # 思考 → 眼睛看向一边 (._.)
    SLEEPY = "sleepy"         # 困倦 → 眼睛半闭 (-_-)
    SURPRISED = "surprised"   # 惊讶 → 眼睛变大 (O_O)
    HAPPY = "happy"           # 开心 → 眼睛闪烁 (★_★)
    CONFUSED = "confused"     # 疑惑 → 大小眼 (o_O)
    BORED = "bored"           # 无聊 → 眼睛下垂 (._.)
    FOCUSED = "focused"       # 专注 → 眼睛缩小 (・_・)
    SHY = "shy"               # 害羞 → 眼睛眯起 (>///<)


class Behavior(Enum):
    """每日随机行为"""
    THROW_TRASH = "throw_trash"         # 扔垃圾
    PRETEND_SLEEP = "pretend_sleep"     # 装睡
    STARING = "staring"                 # 发呆
    YAWN = "yawn"                       # 打哈欠
    STRETCH = "stretch"                 # 伸懒腰
    CHECK_TIME = "check_time"           # 看时间
    DRINK_TEA = "drink_tea"             # 喝奶茶
    READ_DOC = "read_doc"               # 看文档
    TAKE_NOTES = "take_notes"           # 记笔记
    EYE_MASK = "eye_mask"               # 戴眼罩睡觉


class Prop(Enum):
    """道具"""
    MILK_TEA = "milk_tea"       # 奶茶杯
    DOCUMENT = "document"       # 文档
    NOTEBOOK = "notebook"       # 笔记本
    TRASH_CAN = "trash_can"     # 垃圾桶
    EYE_MASK = "eye_mask"       # 眼罩
    PEN = "pen"                 # 笔
    CLOCK = "clock"             # 时钟
    NONE = "none"               # 无道具


# ============================================================
# 表情参数
# ============================================================

@dataclass
class EmotionParams:
    """表情参数 — 控制眼睛形状"""
    left_eye_width: float = 9.0    # 左眼宽度
    left_eye_height: float = 14.0  # 左眼高度
    right_eye_width: float = 9.0   # 右眼宽度
    right_eye_height: float = 14.0 # 右眼高度
    eye_spacing: float = 18.0      # 眼间距
    left_eye_angle: float = 0.0    # 左眼旋转角度
    right_eye_angle: float = 0.0   # 右眼旋转角度
    left_eye_offset_y: float = 0.0 # 左眼Y偏移
    right_eye_offset_y: float = 0.0 # 右眼Y偏移
    mouth_type: str = "none"       # 嘴型: none/line/smile/frown/o/zigzag
    blink_interval: float = 3.0    # 眨眼间隔(秒)
    eye_color: str = "#333"        # 眼睛颜色
    pupil_visible: bool = False    # 是否显示瞳孔(本角色无瞳孔)


# 表情参数映射表
EMOTION_PARAMS = {
    Emotion.SMILE: EmotionParams(
        left_eye_height=10, right_eye_height=10,
        mouth_type="smile", eye_color="#555",
    ),
    Emotion.ANGRY: EmotionParams(
        left_eye_height=6, right_eye_height=6,
        left_eye_angle=-5, right_eye_angle=5,
        mouth_type="zigzag", eye_color="#c00",
    ),
    Emotion.THINKING: EmotionParams(
        left_eye_offset_y=2, right_eye_offset_y=-2,
        mouth_type="line", eye_color="#666",
    ),
    Emotion.SLEEPY: EmotionParams(
        left_eye_height=5, right_eye_height=5,
        mouth_type="frown", eye_color="#888",
        blink_interval=1.5,
    ),
    Emotion.SURPRISED: EmotionParams(
        left_eye_width=12, left_eye_height=18,
        right_eye_width=12, right_eye_height=18,
        mouth_type="o", eye_color="#333",
        blink_interval=5.0,
    ),
    Emotion.HAPPY: EmotionParams(
        left_eye_height=12, right_eye_height=12,
        mouth_type="smile", eye_color="Lemon.BRAND_ORANGE_LIGHT",
        blink_interval=1.0,
    ),
    Emotion.CONFUSED: EmotionParams(
        left_eye_height=14, right_eye_height=8,
        mouth_type="line", eye_color="#666",
    ),
    Emotion.BORED: EmotionParams(
        left_eye_height=8, right_eye_height=8,
        left_eye_offset_y=3, right_eye_offset_y=3,
        mouth_type="line", eye_color="#999",
        blink_interval=4.0,
    ),
    Emotion.FOCUSED: EmotionParams(
        left_eye_width=6, left_eye_height=10,
        right_eye_width=6, right_eye_height=10,
        eye_spacing=16, mouth_type="none",
        eye_color="#333", blink_interval=5.0,
    ),
    Emotion.SHY: EmotionParams(
        left_eye_height=6, right_eye_height=6,
        mouth_type="smile", eye_color="#f88",
        blink_interval=0.5,
    ),
}


# ============================================================
# Agent 角色类
# ============================================================

class AgentCharacter:
    """Agent 数字角色

    管理角色的表情、行为、道具和交互状态。
    单例模式，全局唯一。
    """

    # 每日行为时间表（24小时制）
    DAILY_SCHEDULE = [
        (8, 9, Behavior.STRETCH),        # 8-9点 伸懒腰
        (9, 10, Behavior.READ_DOC),      # 9-10点 看文档
        (10, 11, Behavior.TAKE_NOTES),   # 10-11点 记笔记
        (11, 12, Behavior.CHECK_TIME),   # 11-12点 看时间
        (12, 13, Behavior.DRINK_TEA),    # 12-13点 喝奶茶
        (13, 14, Behavior.STARING),      # 13-14点 发呆
        (14, 15, Behavior.YAWN),         # 14-15点 打哈欠
        (15, 16, Behavior.THROW_TRASH),  # 15-16点 扔垃圾
        (16, 17, Behavior.READ_DOC),     # 16-17点 看文档
        (17, 18, Behavior.CHECK_TIME),   # 17-18点 看时间
        (18, 19, Behavior.DRINK_TEA),    # 18-19点 喝奶茶
        (19, 20, Behavior.STARING),      # 19-20点 发呆
        (20, 21, Behavior.PRETEND_SLEEP),# 20-21点 装睡
        (21, 22, Behavior.YAWN),         # 21-22点 打哈欠
        (22, 23, Behavior.EYE_MASK),     # 22-23点 戴眼罩
    ]

    def __init__(self):
        self._current_emotion = Emotion.SMILE
        self._current_behavior = Behavior.STARING
        self._current_prop = Prop.NONE
        self._click_count = 0
        self._last_click_time = 0.0
        self._click_timeout = 1.0  # 1秒内连续点击视为"多次点击"
        self._emotion_lock = threading.Lock()
        self._behavior_timer = None
        self._idle_counter = 0

        # 行为持续时间
        self._behavior_duration = 5.0  # 行为持续5秒

        # 启动随机行为
        self._start_random_behavior()

    # ---- 交互 ----

    def on_click(self) -> Dict:
        """处理点击事件

        单击 → 微笑
        连续点击(3次+) → 生气
        """
        now = time.time()
        with self._emotion_lock:
            if now - self._last_click_time < self._click_timeout:
                self._click_count += 1
            else:
                self._click_count = 1

            self._last_click_time = now

            if self._click_count >= 3:
                self._current_emotion = Emotion.ANGRY
                emotion = "angry"
            else:
                self._current_emotion = Emotion.SMILE
                emotion = "smile"

        return self.get_state()

    def on_idle(self):
        """空闲时随机表情"""
        self._idle_counter += 1

        if self._idle_counter % 10 == 0:
            # 每10次空闲随机切换表情
            idle_emotions = [
                Emotion.THINKING, Emotion.BORED, Emotion.SLEEPY,
                Emotion.CONFUSED, Emotion.SMILE
            ]
            self._current_emotion = random.choice(idle_emotions)

    def on_task_start(self):
        """任务开始时切换到专注"""
        self._current_emotion = Emotion.FOCUSED
        self._current_prop = Prop.DOCUMENT

    def on_task_complete(self, success: bool = True):
        """任务完成时表情"""
        if success:
            self._current_emotion = Emotion.HAPPY
        else:
            self._current_emotion = Emotion.CONFUSED
        self._current_prop = Prop.NONE

    def on_error(self):
        """错误时表情"""
        self._current_emotion = Emotion.SURPRISED

    # ---- 随机行为 ----

    def _start_random_behavior(self):
        """启动随机行为定时器"""
        def _run():
            while True:
                time.sleep(random.uniform(30, 120))  # 30-120秒随机
                self._trigger_random_behavior()

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _trigger_random_behavior(self):
        """触发随机行为"""
        # 根据当前时间选择行为
        current_hour = time.localtime().tm_hour
        possible_behaviors = [Behavior.STARING, Behavior.YAWN, Behavior.CHECK_TIME]

        for start_h, end_h, behavior in self.DAILY_SCHEDULE:
            if start_h <= current_hour < end_h:
                possible_behaviors.append(behavior)

        self._current_behavior = random.choice(possible_behaviors)

        # 行为携带道具
        prop_map = {
            Behavior.DRINK_TEA: Prop.MILK_TEA,
            Behavior.READ_DOC: Prop.DOCUMENT,
            Behavior.TAKE_NOTES: Prop.NOTEBOOK,
            Behavior.THROW_TRASH: Prop.TRASH_CAN,
            Behavior.EYE_MASK: Prop.EYE_MASK,
            Behavior.CHECK_TIME: Prop.CLOCK,
        }
        self._current_prop = prop_map.get(self._current_behavior, Prop.NONE)

        # 行为持续时间后恢复
        def _reset():
            time.sleep(self._behavior_duration)
            self._current_behavior = Behavior.STARING
            self._current_prop = Prop.NONE
            self._current_emotion = Emotion.SMILE

        threading.Thread(target=_reset, daemon=True).start()

    # ---- 状态 ----

    def get_state(self) -> Dict:
        """获取当前状态（供前端渲染）"""
        params = EMOTION_PARAMS.get(self._current_emotion, EMOTION_PARAMS[Emotion.SMILE])

        return {
            "emotion": self._current_emotion.value,
            "behavior": self._current_behavior.value,
            "prop": self._current_prop.value,
            "eyes": {
                "left": {
                    "width": params.left_eye_width,
                    "height": params.left_eye_height,
                    "angle": params.left_eye_angle,
                    "offset_y": params.left_eye_offset_y,
                },
                "right": {
                    "width": params.right_eye_width,
                    "height": params.right_eye_height,
                    "angle": params.right_eye_angle,
                    "offset_y": params.right_eye_offset_y,
                },
                "spacing": params.eye_spacing,
                "color": params.eye_color,
                "pupil_visible": params.pupil_visible,
            },
            "mouth": params.mouth_type,
            "blink_interval": params.blink_interval,
            "click_count": self._click_count,
        }

    def get_emotion(self) -> str:
        return self._current_emotion.value

    def get_behavior(self) -> str:
        return self._current_behavior.value

    def get_prop(self) -> str:
        return self._current_prop.value


# ============================================================
# 前端渲染脚本生成器
# ============================================================

def generate_character_js() -> str:
    """生成前端角色渲染 JavaScript"""
    return """
// Agent Character Renderer — 数字角色渲染器
// 矩形身体 + 椭圆形眼睛 + 表情变化 + 道具

var _agentCharacter = {
    emotion: 'smile',
    behavior: 'staring',
    prop: 'none',
    eyes: { left: {width:9,height:14,angle:0,offset_y:0}, right: {width:9,height:14,angle:0,offset_y:0}, spacing:18, color:'#333', pupil_visible:false },
    mouth: 'none',
    blinkInterval: 3.0,
    clickCount: 0,
};

function _updateAgentCharacter(state) {
    // 更新角色状态
    if (state) {
        Object.assign(_agentCharacter, state);
        _agentCharacter.eyes = state.eyes || _agentCharacter.eyes;
    }
    _renderAgentCharacter();
}

function _renderAgentCharacter() {
    var container = document.getElementById('agentCharacter');
    if (!container) return;

    var e = _agentCharacter.eyes;
    var html = '<div style="position:relative;width:80px;height:100px;">';

    // 身体（矩形）
    html += '<div style="position:absolute;bottom:0;left:5px;width:70px;height:60px;background:rgba(255,255,255,0.08);border:2px solid rgba(255,255,255,0.2);border-radius:6px;"></div>';

    // 眼睛区域
    html += '<div style="position:absolute;top:15px;left:50%;transform:translateX(-50%);display:flex;gap:' + e.spacing + 'px;">';

    // 左眼
    html += '<div style="width:' + e.left.width + 'px;height:' + e.left.height + 'px;background:' + e.color + ';border-radius:50%;transform:rotate(' + e.left.angle + 'deg) translateY(' + e.left.offset_y + 'px);transition:all 0.3s;"></div>';

    // 右眼
    html += '<div style="width:' + e.right.width + 'px;height:' + e.right.height + 'px;background:' + e.color + ';border-radius:50%;transform:rotate(' + e.right.angle + 'deg) translateY(' + e.right.offset_y + 'px);transition:all 0.3s;"></div>';

    html += '</div>';

    // 嘴
    var mouthHtml = '';
    switch(_agentCharacter.mouth) {
        case 'smile': mouthHtml = '<div style="position:absolute;top:40px;left:50%;transform:translateX(-50%);width:16px;height:8px;border-bottom:2px solid ' + e.color + ';border-radius:0 0 8px 8px;"></div>'; break;
        case 'frown': mouthHtml = '<div style="position:absolute;top:42px;left:50%;transform:translateX(-50%);width:16px;height:8px;border-top:2px solid ' + e.color + ';border-radius:8px 8px 0 0;"></div>'; break;
        case 'o': mouthHtml = '<div style="position:absolute;top:40px;left:50%;transform:translateX(-50%);width:8px;height:8px;border:2px solid ' + e.color + ';border-radius:50%;"></div>'; break;
        case 'line': mouthHtml = '<div style="position:absolute;top:44px;left:50%;transform:translateX(-50%);width:12px;height:0;border-top:2px solid ' + e.color + ';"></div>'; break;
        case 'zigzag': mouthHtml = '<div style="position:absolute;top:42px;left:50%;transform:translateX(-50%);width:14px;height:6px;border-bottom:2px solid ' + e.color + ';border-radius:0;"></div>'; break;
    }
    html += mouthHtml;

    // 道具
    var propHtml = '';
    switch(_agentCharacter.prop) {
        case 'milk_tea': propHtml = '<div style="position:absolute;bottom:5px;right:-5px;width:12px;height:16px;background:rgba(255,154,74,0.3);border:1px solid rgba(255,154,74,0.5);border-radius:4px 4px 2px 2px;"></div>'; break;
        case 'document': propHtml = '<div style="position:absolute;bottom:8px;left:-8px;width:16px;height:12px;background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.3);border-radius:1px;transform:rotate(-5deg);"></div>'; break;
        case 'notebook': propHtml = '<div style="position:absolute;bottom:8px;left:-8px;width:14px;height:18px;background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.3);border-radius:2px;"></div>'; break;
        case 'trash_can': propHtml = '<div style="position:absolute;bottom:0;right:-8px;width:14px;height:16px;background:rgba(255,100,100,0.2);border:1px solid rgba(255,100,100,0.4);border-radius:2px 2px 4px 4px;"></div>'; break;
        case 'eye_mask': propHtml = '<div style="position:absolute;top:10px;left:2px;width:76px;height:24px;background:rgba(0,0,0,0.4);border:1px solid rgba(0,0,0,0.6);border-radius:6px;"></div>'; break;
        case 'clock': propHtml = '<div style="position:absolute;top:0;right:-5px;width:12px;height:12px;border:2px solid rgba(255,255,255,0.4);border-radius:50%;"></div>'; break;
    }
    html += propHtml;

    html += '</div>';
    container.innerHTML = html;
}

// 自动眨眼
setInterval(function() {
    var e = _agentCharacter.eyes;
    var blinkEl = document.querySelector('#agentCharacter');
    if (blinkEl) {
        blinkEl.style.opacity = '0.3';
        setTimeout(function() { if (blinkEl) blinkEl.style.opacity = '1'; }, 100);
    }
}, _agentCharacter.blinkInterval * 1000);
"""


# ============================================================
# 全局单例
# ============================================================

_global_character: Optional[AgentCharacter] = None
_char_lock = threading.Lock()


def get_agent_character() -> AgentCharacter:
    """获取全局 Agent 角色单例"""
    global _global_character
    if _global_character is None:
        with _char_lock:
            if _global_character is None:
                _global_character = AgentCharacter()
    return _global_character


# ============================================================
# 自检
# ============================================================

if __name__ == "__main__":
    char = get_agent_character()

    # 测试表情
    print("=== 表情测试 ===")
    for emotion in Emotion:
        char._current_emotion = emotion
        state = char.get_state()
        eye = state["eyes"]
        print(f"  {emotion.value}: 左眼({eye['left']['width']}×{eye['left']['height']}) "
              f"右眼({eye['right']['width']}×{eye['right']['height']}) "
              f"嘴={state['mouth']}")

    # 测试点击
    print("\n=== 点击测试 ===")
    for i in range(5):
        state = char.on_click()
        print(f"  点击{i+1}: 表情={state['emotion']} 点击次数={state['click_count']}")

    # 测试行为
    print("\n=== 行为测试 ===")
    for behavior in Behavior:
        char._current_behavior = behavior
        char._trigger_random_behavior()
        print(f"  {behavior.value} → 道具={char.get_prop()}")

    # 生成前端 JS
    print("\n=== 前端 JS ===")
    js = generate_character_js()
    print(f"  长度: {len(js)} 字符")
    print(f"  包含 _renderAgentCharacter: {'_renderAgentCharacter' in js}")
    print(f"  包含自动眨眼: {'setInterval' in js}")