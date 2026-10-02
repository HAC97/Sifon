# URL verification (Task 8)

Date: 2026-10-01 (all commands run that day, no cookies, no login, no impersonation workaround).

Command (per URL, from the repo root):
`.\services\downloader\.venv\Scripts\python.exe -m yt_dlp --simulate --no-playlist --print "%(title)s | %(duration)s" <URL>`
(yt-dlp 2026.08.19)

| Site | URL | Result | Kept |
|---|---|---|---|
| YouTube | https://www.youtube.com/watch?v=jNQXAC9IdpU | `ERROR: This video is unavailable` | no, replaced |
| YouTube | https://www.youtube.com/watch?v=BaW_jenozKc | `ERROR: This video is unavailable` | no |
| YouTube | https://www.youtube.com/watch?v=aqz-KE-bpKQ | `Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film \| 635` | yes (Creative Commons Blender film) |
| YouTube | https://www.youtube.com/watch?v=eRsGyueVLvQ | `Sintel - Open Movie by Blender Foundation \| 888` | works, not used (longer) |
| YouTube | https://www.youtube.com/watch?v=YE7VzlLtp-4 | `Big Buck Bunny \| 597` | works, not used |
| Vimeo | https://vimeo.com/56015672 | `ERROR: The web client only works when logged-in` (plus warning: no impersonate target available) | yes, kept as is: real failure |
| Vimeo | https://vimeo.com/22439234, /76979871, /1084537, /148751763 | same `only works when logged-in` error | no |
| SoundCloud | https://soundcloud.com/ethmusic/lostin-powers-she-so-heavy | `Lostin Powers - She so Heavy (SneakPreview) Adrian Ackers Blueprint 1 \| 143.206` | yes |
| archive.org | https://archive.org/details/Popeye_forPresident | `Popeye for President \| 370.2` | yes |
| Dailymotion | http://www.dailymotion.com/video/x5kesuj | `ERROR: The extractor is attempting impersonation, but none of these impersonate targets are available: firefox` | yes, kept as is: real failure |
| Dailymotion | https://www.dailymotion.com/video/x2iuewm, xwh1w2, x8jvaoo | `ERROR: Not found.` | no |
| Dailymotion | https://www.dailymotion.com/video/x7tgad0 | same impersonation error as x5kesuj | no |

Notes:
- Vimeo and Dailymotion fail for every URL tried, for environmental reasons (Vimeo web client requires login; Dailymotion extractor requires a curl_cffi impersonation target, not installed). No other public URL of those sites changes the outcome, so the original URLs stay in the eval and fail honestly. We do not use cookies or install impersonation to get around it.
