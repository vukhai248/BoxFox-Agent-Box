# ==============================================================================
# BoxFox Agent Box — Image lõi của AI Computer (sandbox container)
# Thiết kế theo docs/plan/agent-box-plan.md: mục 7.4 (6 quy tắc), 7.4.1 (công tắc
# mạng), 7.5 (thành phần trong box), 12.3.1 (triết lý máy trống).
#
# Triết lý "MÁY TRỐNG":
#   BAKE (hạ tầng của chính agent — không thể chờ agent tự cài tay chân mình):
#     - Chromium + Playwright driver (ghim phiên bản — tái lập 13.6)
#     - Xvfb (màn hình ảo) + x11vnc (người dùng xem qua VNC — khung ④)
#     - code-server (VS Code trên web — khung editor của người dùng)
#     - git + công cụ dòng lệnh cơ bản
#   KHÔNG BAKE (stack của dự án người dùng — agent tự cài khi cần, qua công tắc
#   mạng 7.4.1):
#     - Node.js, các framework, JDK, Rust... — KHÔNG có sẵn ở đây.
#
# Ghi chú về Python: python3 hệ thống (Ubuntu 24.04) hiện diện CHỈ với vai trò
# máy chạy driver Playwright (/opt/pw-driver). Đây không phải stack phát triển;
# agent hoàn toàn có thể cài phiên bản Python khác theo yêu cầu người dùng.
#
# Hardening (quy tắc ⑥ preview): chạy non-root `agent`, không sudo,
# KHÔNG có biến môi trường chứa khóa API, KHÔNG mount $HOME (quy tắc ⑤).
# ==============================================================================

FROM ubuntu:24.04

# --- Phiên bản ghim (đổi = hành động có chủ ý + phải chạy lại smoke-test) -----
ARG PLAYWRIGHT_VERSION=1.49.0
ARG CODE_SERVER_VERSION=4.97.2

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Ho_Chi_Minh \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    DISPLAY=:99

# --- Lớp 1: công cụ hệ thống cơ bản + màn hình ảo ----------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget gnupg unzip xz-utils \
      git \
      xvfb x11vnc \
      fonts-dejavu-core fonts-liberation \
      python3 python3-venv \
      gosu iptables \
    && rm -rf /var/lib/apt/lists/*

# --- Lớp 2: user thường `agent` (quy tắc ⑥ — không root, không sudo) ---------
# Ubuntu 24.04 tạo sẵn user `ubuntu` chiếm UID/GID 1000 → dọn đúng đối tượng đó
# trước khi cấp lại 1000 cho `agent` (getent kiểm tra, không xóa mù).
RUN if getent passwd ubuntu >/dev/null 2>&1; then userdel -r ubuntu || true; fi \
    && if getent group ubuntu >/dev/null 2>&1; then groupdel ubuntu || true; fi \
    && groupadd --gid 1000 agent \
    && useradd --uid 1000 --gid agent --create-home --shell /bin/bash agent

# --- Lớp 3: Playwright driver + Chromium (ghim phiên bản) --------------------
RUN python3 -m venv /opt/pw-driver \
    && /opt/pw-driver/bin/pip install --no-cache-dir "playwright==${PLAYWRIGHT_VERSION}"
ENV PATH="/opt/pw-driver/bin:${PATH}"

# `install --with-deps` tự chạy apt để cài thư viện hệ thống của Chromium.
# Chromium rơi vào PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright.
RUN playwright install --with-deps chromium \
    && mkdir -p /opt/ms-playwright \
    && chown -R agent:agent /opt/ms-playwright \
    && playwright --version | grep -q "${PLAYWRIGHT_VERSION}"  # khẳng định ghim đúng bản

# --- Lớp 3.5: websockify — cầu WebSocket cho noVNC (khung ④, mục 12.6) -------
# Lớp riêng để không phá cache của các lớp nặng (Chromium) khi chỉnh sửa sau.
RUN apt-get update && apt-get install -y --no-install-recommends websockify \
    && rm -rf /var/lib/apt/lists/*

# --- Lớp 4: code-server (VS Code trên web) -----------------------------------
RUN curl -fsSL https://code-server.dev/install.sh \
      | sh -s -- --version "${CODE_SERVER_VERSION}" --method standalone --prefix /opt/code-server \
    && ln -s /opt/code-server/bin/code-server /usr/local/bin/code-server

# --- Lớp 5: công tắc mạng + workspace + entrypoint ----------------------------
COPY box-entrypoint.sh /usr/local/bin/box-entrypoint.sh
COPY box-firewall /usr/local/sbin/box-firewall
RUN chmod +x /usr/local/bin/box-entrypoint.sh /usr/local/sbin/box-firewall \
    && mkdir -p /home/agent/workspace /home/agent/.code-server \
    && chown -R agent:agent /home/agent

USER agent
WORKDIR /home/agent/workspace

EXPOSE 5900 8080
ENTRYPOINT ["box-entrypoint.sh"]
