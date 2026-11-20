# Lab records

One folder per classroom session: result report, Jetson logs (`robot/logs/`
copied back with scp), and anything sent along with them.

| Session | Folder | Notes |
|---|---|---|
| 2026-11-18 | [`20261118/`](20261118/) | First run: Foxy install, bringup, C920 vision worker. Issue index: `README_이슈색인.md` |
| 2026-11-20 | [`20261120/`](20261120/) | LDS-02 bringup, D455 build and depth check. Summary: `1120_진행정리.pdf`; next lab: `다음실습_D455_실행순서.pdf` |

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
