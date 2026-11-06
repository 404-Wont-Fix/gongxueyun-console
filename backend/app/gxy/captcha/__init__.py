"""Captcha solvers.

* slider (login)  — pure OpenCV template matching, always available.
* click-word (attendance ``msg == 302``) — optional ONNX models. When they are
  absent we do **not** guess: the challenge is surfaced to the web UI so the
  user can click the characters themselves.
"""

from __future__ import annotations

import base64
import json
import random
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import CaptchaError, CaptchaUnavailable

try:  # optional at import time so the rest of the app runs without OpenCV
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - exercised only on slim images
    cv2 = None
    np = None


def _b64decode(value: str) -> bytes:
    if not value:
        raise CaptchaError("empty captcha image")
    try:
        return base64.b64decode(value)
    except Exception as exc:  # pragma: no cover - malformed server data
        raise CaptchaError("captcha image is not valid base64") from exc


def png_width(raw: bytes) -> int:
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise CaptchaError("captcha image is not a PNG")
    return struct.unpack(">I", raw[16:20])[0]


@dataclass
class SliderSolver:
    """Canny + matchTemplate, the same approach the newer repositories use."""

    def available(self) -> bool:
        return cv2 is not None and np is not None

    def solve(self, jigsaw_b64: str, background_b64: str) -> dict[str, float]:
        if not self.available():
            raise CaptchaUnavailable("未安装 OpenCV，无法自动识别滑块验证码")
        jigsaw_raw = _b64decode(jigsaw_b64)
        background_raw = _b64decode(background_b64)
        target = cv2.imdecode(np.frombuffer(jigsaw_raw, np.uint8), cv2.IMREAD_ANYCOLOR)
        background = cv2.imdecode(np.frombuffer(background_raw, np.uint8), cv2.IMREAD_ANYCOLOR)
        if target is None or background is None:
            raise CaptchaError("滑块图片解码失败")

        background_edges = cv2.cvtColor(cv2.Canny(background, 100, 200), cv2.COLOR_GRAY2RGB)
        target_edges = cv2.cvtColor(cv2.Canny(target, 100, 200), cv2.COLOR_GRAY2RGB)
        result = cv2.matchTemplate(background_edges, target_edges, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score < 0.2:
            raise CaptchaError("滑块匹配置信度过低")
        target_width = target_edges.shape[1]
        target_center = location[0] + target_width / 2
        distance = target_center - target_width / 2
        return {"x": round(distance + random.uniform(-0.1, 0.1), 1), "y": 5}


@dataclass
class ClickWordSolver:
    """YOLOv5n detector + small OCR classifier, loaded from a local model dir."""

    model_dir: Path | None = None

    def _session(self, name: str):
        if not self.model_dir:
            raise CaptchaUnavailable("未配置点选验证码模型目录")
        path = self.model_dir / name
        if not path.exists():
            raise CaptchaUnavailable(f"缺少模型文件: {name}")
        try:
            import onnxruntime  # type: ignore
        except Exception as exc:
            raise CaptchaUnavailable("未安装 onnxruntime，无法自动识别点选验证码") from exc
        providers = ["CPUExecutionProvider"]
        return onnxruntime.InferenceSession(str(path), providers=providers)

    def available(self) -> bool:
        if not self.model_dir or cv2 is None or np is None:
            return False
        if not (self.model_dir / "yolov5n.onnx").exists():
            return False
        if not (self.model_dir / "ocr.onnx").exists():
            return False
        try:
            import onnxruntime  # noqa: F401
        except Exception:
            return False
        return True

    def solve(self, image_b64: str, words: list[str]) -> list[dict[str, int]]:
        if not self.available():
            raise CaptchaUnavailable("点选验证码自动识别未启用")
        image = cv2.imdecode(np.frombuffer(_b64decode(image_b64), np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise CaptchaError("点选验证码图片解码失败")
        boxes = self._detect(image)
        recognised: dict[str, list[int]] = {}
        for box in boxes:
            x1, y1, x2, y2 = box
            text = self._ocr(image[y1:y2, x1:x2])
            recognised.setdefault(text, box)
        points: list[dict[str, int]] = []
        for word in words:
            box = recognised.get(word)
            if not box:
                raise CaptchaError(f"未在图片中识别到字符: {word}")
            points.append(
                {
                    "x": random.randint(box[0], max(box[0], box[2] - 1)),
                    "y": random.randint(box[1], max(box[1], box[3] - 1)),
                }
            )
        return points

    def _detect(self, image) -> list[list[int]]:
        session = self._session("yolov5n.onnx")
        scale = min(640 / image.shape[1], 640 / image.shape[0])
        resized = cv2.resize(image, (int(image.shape[1] * scale), int(image.shape[0] * scale)))
        canvas = np.full((640, 640, 3), 128, dtype=np.uint8)
        dx = (640 - resized.shape[0]) // 2
        dy = (640 - resized.shape[1]) // 2
        canvas[dx : dx + resized.shape[0], dy : dy + resized.shape[1]] = resized
        tensor = np.expand_dims(canvas.transpose((2, 0, 1)), axis=0).astype(np.float32) / 255.0
        output = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
        boxes: list[list[int]] = []
        for row in output:
            confidence = float(row[4])
            if confidence < 0.5:
                continue
            xc, yc, w, h = (float(v) for v in row[:4])
            x1 = int((xc - w / 2 - dy) / scale)
            y1 = int((yc - h / 2 - dx) / scale)
            x2 = int((xc + w / 2 - dy) / scale)
            y2 = int((yc + h / 2 - dx) / scale)
            boxes.append([x1, y1, x2, y2])
        return boxes

    def _ocr(self, patch) -> str:
        session = self._session("ocr.onnx")
        charset = _OCR_CHARSET
        tensor = np.expand_dims(
            cv2.cvtColor(cv2.resize(patch, (64, 64)), cv2.COLOR_BGR2RGB)
            .transpose((2, 0, 1))
            .astype(np.float32)
            / 255.0,
            axis=0,
        )
        indexes = session.run(None, {session.get_inputs()[0].name: tensor})[1]
        return "".join(charset[i] for i in indexes if 0 <= i < len(charset))


# The classifier's label order is fixed by the exported ONNX model.
_OCR_CHARSET = list(
    "士候之科孩雪万章导治亲社所似验习吃历写业为睛睡将林法你观信掉觉站确老方道海性好感女术如重细青流心包越且风哥菜劳必阶代令志国们记知谁讲眼提由民怎度村没呀许以四政点离说带关答出放告夜识兴做难八叶月马办行三最小亮作晚义活公旁色看从话系高水您到装中研雨住因少原什片准脚张深力让顶石山类野阵赶见七立整屋再读相弟两接种车近外几停认特战化子定边多产形她衣共音分级别千连理往先队围满在领画他反花农被名这席众很渐乡极实城取题儿响那主进去思找总应船身牛歌团爬岁着冲早利受忽苦也表通有像现对头开般呼又的把帮收军怕饭或就年背来革压斗位房飞都块跳变今命区爱门入九动根南造其者便每事座算然笑阳半大是会一非树旧里至无问发河物东叔它百拿叫明刚脸干样呢更底忙我结地界草论还轻数世只用于长个光此沙面白转哪想件文未啦口十人各并敌打古合完啊线回嘴究岸听内土跑日平咱快坚真够工些已争得望伟却处但过唱时热走书不起神使本自倒比前新直经解步胜次该六后报体家急际五北等员何火吗机当么天枪量意同决钱情手强全了可果气加学息黑刻而慢紧照指改上运声二吧己字才教于向要建展句史给坐和第成落跟群星生部送服穿友下拉任太常场敢清路破传空师切条"
)


@dataclass
class CaptchaSolver:
    slider: SliderSolver = field(default_factory=SliderSolver)
    clickword: ClickWordSolver = field(default_factory=ClickWordSolver)

    @classmethod
    def from_settings(cls, model_dir: Path | None) -> "CaptchaSolver":
        return cls(slider=SliderSolver(), clickword=ClickWordSolver(model_dir=model_dir))

    def describe(self) -> dict[str, Any]:
        return {
            "slider_ready": self.slider.available(),
            "clickword_ready": self.clickword.available(),
            "clickword_model_dir": str(self.clickword.model_dir or ""),
        }

    def solve_slider(self, jigsaw_b64: str, background_b64: str) -> str:
        return json.dumps(self.slider.solve(jigsaw_b64, background_b64), separators=(",", ":"))

    def solve_clickword(self, image_b64: str, words: list[str]) -> str:
        return json.dumps(self.clickword.solve(image_b64, words), separators=(",", ":"))
