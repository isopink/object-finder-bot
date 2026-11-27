# Lab records

One folder per classroom session: result report, Jetson logs (`robot/logs/`
copied back with scp), and anything sent along with them.

| Session | Folder | Notes |
|---|---|---|
| 2026-11-18 | [`20261118/`](20261118/) | First run: Foxy install, bringup, C920 vision worker. Issue index: `README_이슈색인.md` |
| 2026-11-20 | [`20261120/`](20261120/) | LDS-02 bringup, D455 build and depth check. Summary: `1120_진행정리.pdf`; next lab: `다음실습_D455_실행순서.pdf` |
| 2026-11-24 | [`20261124/`](20261124/) | NanoOWL detector, spoken queries from the laptop, mast LiDAR filter. Team notes: `README_먼저읽기.md`, photos in `사진/` |
| 2026-11-25 | [`20261125/`](20261125/) | Team session: odometry heading option, live SLAM map, the five map images in `maps/` |
| 2026-11-27 | [`20261127/`](20261127/) | Team session: Nav2 on a Cartographer map (Foxy params, wide DDS discovery, aisle-only nav map) |
| 2026-11-28 | [`20261128/`](20261128/) | **First full run**: remember a cup or laptop, ask, drive with four commands, re-check. 3 of 3 queries found. D455 depth, own wheel odometry, AMCL on the full map. How to run it: `README.md` |

Problems hit in the lab and how they were solved: [`트러블슈팅_기록.md`](트러블슈팅_기록.md).

## 2026-11-18 patches

The three patches in `20261118/patches/` are already on `main`, with their
original author:

- `d90a913` robot: fixes from the first classroom run
- `c118f9b` Add spoken queries: robot/voice.sh + scripts/voice_query.py
- `0bbc60f` Demo helpers: RealSense build, waypoint patrol, whisper_trt option

So in step 1 of `20261118/1120_실행순서.pdf`, skip the `scp` and `git apply`
lines. On the Jetson, run these instead:

```bash
cd ~/object-finder-bot
git checkout -- robot/env.sh robot/install_foxy_jetson.sh   # drop the 11/18 hand edits
git pull
sudo cp robot/udev/99-ofb-robot.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger
```

The patch files are kept for reference only. They have CRLF line endings, so
`git apply` on them fails.

## 2026-11-24 team notes

`20261124/README_먼저읽기.md` is the team's note from that day. Its two patches
(NanoOWL `--detector owl`, LiDAR mast filter `OFB_SCAN_MIN`) are already on
`main` with their author, so skip its "패치 적용" step; on the Jetson just
`git pull`. The laptop voice tool from the note is in
[`scripts/laptop_voice/`](../../scripts/laptop_voice/) (double-click
`음성질문.cmd`). Changes made to it after the note:

- prefers Python 3.12, 3.11, 3.10 (faster-whisper has no wheels for 3.14 yet)
- installs `certifi`; the lab CA now overrides a `SSL_CERT_FILE` set by conda,
  and the Xet downloader is switched off (it ignores the CA bundle)
- the question goes out through a small rclpy publisher that waits for the
  finder instead of `ros2 topic pub --once`: about 5 s instead of 12 s, and it
  says so when nothing listens on `/query`

The camera for the demo is the C920 (`nodepth`); the D455 (`depth`) stays
installed.
