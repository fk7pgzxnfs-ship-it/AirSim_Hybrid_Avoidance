# -*- coding: utf-8 -*-
"""gen_scene.py - v3 场景生成器 CLI

把场景 yaml 转成 UE LoadScene 用的 jsonc，并生成 2D 预览图。

用法:
  python scripts/tools/gen_scene.py --scene config/scenes/scene_100x10.yaml
  python scripts/tools/gen_scene.py --scene config/scenes/xxx.yaml --preview logs/scene_preview.png
  python scripts/tools/gen_scene.py --scene config/scenes/xxx.yaml --out config/scenes/generated/xxx.jsonc
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scene_config import SceneConfig


def main():
    import argparse
    ap = argparse.ArgumentParser(description="v3 场景生成器")
    ap.add_argument("--scene", required=True, help="场景 yaml 路径")
    ap.add_argument("--out", default=None, help="UE jsonc 输出路径（默认 config/scenes/generated/<id>.jsonc）")
    ap.add_argument("--preview", default=None, help="预览图 PNG 输出路径（可选）")
    args = ap.parse_args()

    scene = SceneConfig.load(args.scene)
    print("=" * 55)
    print("场景: %s" % scene.id)
    print("地图: x[%s,%s] y[%s,%s] 分辨率 %.1fm" % (
        scene.x_min, scene.x_max, scene.y_min, scene.y_max, scene.resolution))
    print("起点: %s   终点: %s   路线: %s" % (
        scene.start.tolist(), scene.goal.tolist(), scene.route_mode))
    print("障碍物: %d 个" % len(scene.obstacles))
    for o in scene.obstacles:
        print("  - %s @ (%s, %s) %sx%sx%s m" % (
            o.name, o.x, o.y, o.w, o.h, o.height))
    print("=" * 55)

    errs = scene.validate()
    if errs:
        print("校验失败:")
        for e in errs:
            print("  - %s" % e)
        sys.exit(1)
    print("校验通过")

    r = scene.check_reachable()
    print("可达性: %s" % r["message"])
    if not r["reachable"]:
        print("警告: 布局不可达，不建议直接飞行。")

    out = scene.dump_ue_scene(args.out)
    print("UE 场景已生成: %s" % out)

    if args.preview:
        p = scene.to_preview(args.preview, title="场景预览: %s" % scene.id)
        print("预览图已生成: %s" % p)


if __name__ == "__main__":
    main()
