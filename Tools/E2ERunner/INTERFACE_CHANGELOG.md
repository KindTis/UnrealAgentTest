# E2ERunner Interface Changelog

## 2026-03-22

### Added
- Planned `GET /capture/screenshot` contract for viewport-only capture.
- Planned bridge file contract:
  - `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/observe.json`
  - `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/decide.json`
  - `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/bridge.lock`

### Contract Notes
- Capture default: `height=360`, `preserve_aspect_ratio=true`, `jpeg_quality=60`.
- Capture response must include `captured_session_id` and `viewport_state`.
- `viewport_state` fields:
  - `is_minimized`
  - `is_occluded`
  - `is_focused`
  - `viewport_width`
  - `viewport_height`
  - `capture_source` (`game_viewport|pie_viewport`)

### Failure Codes
- `viewport_minimized`
- `viewport_occluded`
- `capture_timeout`
- `capture_unavailable`
