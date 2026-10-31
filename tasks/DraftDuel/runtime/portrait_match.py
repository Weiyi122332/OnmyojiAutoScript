"""本局头像在手牌及上阵头像内的缩放匹配，不依赖设备。"""
import cv2
import numpy as np

# 2026-10-31 两张 MuMu 截图校准：shikigami_head[0] -> fight_shikigami[0]。
# 42x44 头像按 0.986 缩放为 41x43，TM_CCOEFF_NORMED 得分 0.911663。
FIGHT_PORTRAIT_SCALE = 0.986
# 同两张截图五组手牌共同校准，以五组最低正确匹配分数最大为目标。
# 1.58 倍时最低分 0.681102，五组均正确对应并超过手牌阈值 0.65。
HAND_PORTRAIT_SCALE = 1.58


def locate_portrait(template, image, area, *, scale=HAND_PORTRAIT_SCALE, threshold=0.65):
    """在整个 back 内定位目标头像，返回截图坐标 (x,y,w,h) 和得分。"""
    x, y, w, h = (int(round(v)) for v in area)
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > image.shape[1] or y + h > image.shape[0]:
        return None
    if template is None or not template.size:
        return None
    resized = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    th, tw = resized.shape[:2]
    if th > h or tw > w:
        return None
    scores = cv2.matchTemplate(image[y:y+h, x:x+w], resized, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(scores)
    if score < threshold:
        return None
    return (x + location[0], y + location[1], tw, th), float(score)


def portrait_score(template, region, scale=None):
    best = -1.0
    if template is None or region is None or not template.size or not region.size:
        return best
    for factor in ((scale,) if scale is not None else np.arange(0.6, 2.51, 0.01)):
        resized = cv2.resize(template, None, fx=float(factor), fy=float(factor),
                             interpolation=cv2.INTER_LINEAR)
        if resized.shape[0] > region.shape[0] or resized.shape[1] > region.shape[1]:
            continue
        score = cv2.minMaxLoc(cv2.matchTemplate(region, resized, cv2.TM_CCOEFF_NORMED))[1]
        best = max(best, score)
    return best


def identify_portrait(region, named_heads, threshold=0.8, margin=0.05, *, scale=None):
    ranked = sorted(((portrait_score(head, region, scale=scale), name) for name, head in named_heads),
                    reverse=True)
    if not ranked or ranked[0][0] < threshold:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < margin:
        return None
    return ranked[0][1]
