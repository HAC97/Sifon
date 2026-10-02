# URL verification (Task 8)

Date: 2026-10-01 (all commands run that day, no cookies, no login). The first table was produced before `curl_cffi` was installed (no impersonation target available). The "Re-check" section below was run afterwards, once `yt-dlp[default,curl-cffi]` had been added to requirements and installed; where it differs, the re-check is the final state.

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
| Vimeo | https://vimeo.com/56015672 | `ERROR: The web client only works when logged-in` (plus warning: no impersonate target available) | yes, kept in the eval (superseded, see re-check: now a 404, dead URL) |
| Vimeo | https://vimeo.com/22439234, /76979871, /1084537, /148751763 | same `only works when logged-in` error | no (superseded, see re-check: 148751763 is now a 404, the others stay login-only) |
| SoundCloud | https://soundcloud.com/ethmusic/lostin-powers-she-so-heavy | `Lostin Powers - She so Heavy (SneakPreview) Adrian Ackers Blueprint 1 \| 143.206` | yes |
| archive.org | https://archive.org/details/Popeye_forPresident | `Popeye for President \| 370.2` | yes |
| Dailymotion | http://www.dailymotion.com/video/x5kesuj | `ERROR: The extractor is attempting impersonation, but none of these impersonate targets are available: firefox` | yes, kept in the eval (superseded, see re-check: works once curl-cffi is installed) |
| Dailymotion | https://www.dailymotion.com/video/x2iuewm, xwh1w2, x8jvaoo | `ERROR: Not found.` | no |
| Dailymotion | https://www.dailymotion.com/video/x7tgad0 | same impersonation error as x5kesuj | no (superseded, not re-checked after the install) |

Re-check after adding curl_cffi (2026-10-01, same `--simulate` command):
- `services/downloader/requirements.txt` now has `yt-dlp[default,curl-cffi]` and the extras were installed in the venv (curl-cffi 0.16.3), so impersonation is available through the normal yt-dlp mechanism. No cookies, no login, no other workaround.
- Dailymotion http://www.dailymotion.com/video/x5kesuj: now works, `Office Christmas Party Review - Jason Bateman, Olivia Munn, T.J. Miller | 187`. Kept.
- Vimeo https://vimeo.com/56015672: `ERROR: Unable to download webpage: HTTP Error 404: Not Found` (video no longer exists). Other Vimeo URLs after the install: 148751763 and 347119375 give 404; 22439234, 76979871, 1084537, 90509568 give `The web client only works when logged-in`. No public Vimeo URL found that works without login, so the Vimeo cases stay in the eval as honest FAILs (not replaced by another site).

Conclusion: 7 Vimeo URLs were tried (56015672, 22439234, 76979871, 1084537, 148751763, 90509568, 347119375), none was usable (404 or login-only), so the 2 Vimeo eval cases are kept and fail on purpose. The eval margin is thin: 9 of 11 = 82% against an 80% threshold. Three later runs the same day gave 73%, 64% and 64% (archive.org did not answer from this machine; one YouTube audio case failed once), so the threshold is not confirmed as stable and the eval must be re-run when the sites are reachable.

Earlier notes (before the install): Dailymotion failed with the missing impersonation target, Vimeo with the login error.
