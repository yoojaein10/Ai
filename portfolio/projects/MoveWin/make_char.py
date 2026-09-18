# -*- coding: utf-8 -*-
"""Chroma-key green removal for MoveWin character image."""

from PIL import Image
import numpy as np
from collections import deque


def process(input_path: str, output_path: str):
    img = Image.open(input_path).convert('RGBA')
    arr = np.array(img, dtype=np.float32)
    h, w = arr.shape[:2]
    print(f"원본 크기: {w}x{h}")

    R = arr[:, :, 0] / 255.0
    G = arr[:, :, 1] / 255.0
    B = arr[:, :, 2] / 255.0

    # Greenness = G - max(R, B)
    # 초록 배경:  greenness 높음 (0.5~1.0)
    # 민트 하이라이트: G≈B 이므로 greenness 낮음 (0.05 이하)
    greenness = G - np.maximum(R, B)

    # tolerance 넉넉하게: hard=0.35, soft=0.12
    hard = 0.35
    soft = 0.12

    alpha_mult = np.ones((h, w), dtype=np.float32)
    alpha_mult[greenness >= hard] = 0.0

    feather = (greenness > soft) & (greenness < hard)
    t = (greenness[feather] - soft) / (hard - soft)
    alpha_mult[feather] = 1.0 - t

    result = arr.copy()
    result[:, :, 3] = np.clip(result[:, :, 3] / 255.0 * alpha_mult, 0, 1) * 255

    # Green spill suppression: 반투명 엣지에서 초록 채널 억제
    edge = (alpha_mult > 0.02) & (alpha_mult < 0.98)
    result[edge, 1] = np.clip(result[edge, 1] - greenness[edge] * 90, 0, 255)

    result = result.astype(np.uint8)

    # 오른쪽 아래 반짝이 제거 + 고립된 잔상 제거
    # BFS: 캐릭터 중심(head 부근)에서 연결된 픽셀만 보존
    non_trans = result[:, :, 3] > 20

    # 시드: 이미지 위쪽 중앙 (머리 부근)
    seed_y, seed_x = h // 5, w // 2
    # 시드가 투명이면 근방에서 탐색
    if not non_trans[seed_y, seed_x]:
        found = False
        for dy in range(-40, 40):
            for dx in range(-40, 40):
                sy, sx = seed_y + dy, seed_x + dx
                if 0 <= sy < h and 0 <= sx < w and non_trans[sy, sx]:
                    seed_y, seed_x = sy, sx
                    found = True
                    break
            if found:
                break

    keep = np.zeros((h, w), dtype=bool)
    visited = np.zeros((h, w), dtype=bool)
    q: deque = deque([(seed_y, seed_x)])
    visited[seed_y, seed_x] = True
    keep[seed_y, seed_x] = True

    while q:
        y, x = q.popleft()
        for dy, dx in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and non_trans[ny, nx]:
                visited[ny, nx] = True
                keep[ny, nx] = True
                q.append((ny, nx))

    result[~keep, 3] = 0

    Image.fromarray(result, 'RGBA').save(output_path)
    kept = keep.sum()
    total = h * w
    print(f"저장 완료: {output_path}")
    print(f"캐릭터 픽셀: {kept:,} / 전체: {total:,} ({kept/total*100:.1f}%)")


if __name__ == '__main__':
    process(
        'C:\\Users\\PUBLIC_USER\\Downloads\\Gemini_Generated_Image_yj3n5zyj3n5zyj3n.png',
        r'D:\AI\Claude\MoveWin\char.png',
    )
