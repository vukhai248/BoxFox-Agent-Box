# ==============================================================================
# BoxFox Agent Box — Image lõi của AI Computer (sandbox container)
# Thiết kế theo docs/plan/agent-box-plan.md: mục 7.4 (6 quy tắc), 7.4.1 (công tắc
# mạng), 7.5 (thành phần trong box), 12.3.1 (triết lý máy trống).
#
# Triết lý "MÁY TRỐNG":
#   BAKE (hạ tầng của chính agent — không thể chờ agent tự cài tay chân mình):
#     - Chromium + Playwright driver (ghim phiên bản — tái lập 13.6)
#     - Xvnc (TigerVNC) — X server có RFB tích hợp: MỘT tiến trình thay cho
#       Xvfb + x11vnc, và RandR động nên desktop đổi phân giải THẬT theo kích
#       thước khung ④ khi người dùng kéo panel (Xvfb có framebuffer cố định nên
#       chỉ scale được ảnh ⇒ sinh viền đen)
#     - XFCE (môi trường desktop) + trình xem ảnh/văn bản
#     - code-server (VS Code trên WEB — editor duy nhất trong box)
#     - git + công cụ dòng lệnh cơ bản
#
# Vì sao BAKE cả một desktop: mục 7.5 ghi "Trình xem/render file (ảnh, markdown,
# PDF) — Có, cơ bản", và mục 12.3.1 hứa người dùng NHÌN được máy đang làm gì.
# Một X server trống trơn không đáp ứng cả hai: mở khung ④ ra chỉ thấy màu đen,
# và Chromium chạy toàn màn hình thì không có cách nào thoát ra để xem file hay
# mở cửa sổ khác. Có desktop thì Chromium chỉ là MỘT ứng dụng trong máy, đúng
# như một máy tính thật — và người dùng có taskbar, file manager, terminal,
# trình xem ảnh để tự kiểm tra kết quả agent làm.
#
# Vì sao KHÔNG có VS Code bản desktop (Electron): đo trên chính image này, bản
# desktop tốn ~460 MB RAM và ~437 MB image, lại phải đi qua Xvnc →
# websockify → noVNC mới nhìn được, tức mỗi lần gõ một ký tự là một lượt truyền
# ẢNH. code-server đưa cùng một editor tới trình duyệt của người dùng dưới dạng
# text, tốn ~172 MB RAM trong box và không cần một pixel nào của desktop. Giao
# diện web có tab IDE nhúng thẳng code-server nên đây là đường vào chính; desktop
# XFCE giữ lại cho Chromium, xem file và bằng chứng "màn hình luôn không tin
# được" (quy tắc M1, mục 8.5).
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

# --- Lớp 1: công cụ hệ thống cơ bản + màn hình ảo (Xvnc — X server CÓ RFB) ---
# `tigervnc-standalone-server` cung cấp /usr/bin/Xvnc: X server nói luôn giao
# thức RFB, thay CẢ Xvfb LẪN x11vnc. Lý do bắt buộc phải đổi: Xvfb báo
# `xrandr → maximum 1280x800` (BẰNG kích thước khởi tạo, đúng một mode) nên
# không thể đổi phân giải sau khi chạy, còn x11vnc chỉ THEO DÕI xrandr phía
# server, không nhận `SetDesktopSize` do client gửi lên. Xvnc báo
# `maximum 32768x32768` và nhận `SetDesktopSize` ⇒ noVNC xin đổi phân giải khớp
# panel được (đã đo: 1600x900, 700x950, 2400x1300, 1173x812 đều khớp chính xác).
# Chi phí: +~10 MB, bỏ được xvfb + x11vnc ~4 MB ⇒ net ~+6 MB.
# Công cụ capture/record theo cửa sổ X11 (xem docs/architecture/screen-capture.md):
#   xdotool     : windowactivate/windowraise — raise cửa sổ trước khi chụp
#   wmctrl      : liệt kê cửa sổ -lx + activate
#   imagemagick : lệnh `import` chụp ảnh -window <id> / root
#   ffmpeg      : quay x11grab -window_id (bản Ubuntu 24.04 có sẵn libx264, đã xác minh)
#   x11-utils   : xprop (đọc _NET_WM_PID/_NET_WM_STATE), xwininfo (lấy geometry)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget gnupg unzip xz-utils \
      git \
      tigervnc-standalone-server \
      x11-xserver-utils \
      xdotool wmctrl imagemagick ffmpeg \
      x11-utils \
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

# --- Lớp 4.5: môi trường desktop XFCE ----------------------------------------
# Chọn XFCE chứ không phải GNOME/KDE: nhẹ (không compositing nặng, không
# systemd), chạy được trên Xvnc không GPU, và vẫn có đủ thứ một máy tính thật
# phải có — taskbar, menu ứng dụng, quản lý cửa sổ, file manager.
#   xfce4-session/xfwm4/xfdesktop4/xfce4-panel : desktop + taskbar + WM
#   thunar + ristretto + mousepad              : file manager, xem ảnh, xem/sửa
#                                                văn bản & markdown (mục 7.5)
#   dbus-x11                                   : XFCE cần session bus
#   xfce4-appfinder                            : tìm/chạy ứng dụng
#   xdg-utils                                  : mở file bằng ứng dụng mặc định
#
# THEME + ICON (bắt buộc, không phải trang trí): XFCE trần dùng theme GTK
# "Adwaita" SÁNG và không có icon theme đầy đủ nào ngoài `hicolor` (gần như
# trống) → panel trắng chói đập vào giao diện tối của web UI, và MỌI icon rơi về
# ô vuông xanh vô nghĩa. Người dùng mở khung ④ ra không nhận ra đâu là Terminal
# đâu là trình duyệt. Đây là rào cản trải nghiệm ngay giây đầu tiên, nên hai gói
# dưới đây thuộc hạ tầng chứ không phải tuỳ chọn:
#   elementary-xfce-icon-theme (~14 MB) : icon set của Xubuntu — thư mục,
#     Terminal, trình duyệt, file có logo thật, y như một máy Linux bình thường
#   greybird-gtk-theme (~5 MB)          : theme tối chuẩn Xubuntu cho cả GTK và
#     xfwm4, hòa với nền #0f172a của panel khung ④
# adwaita-icon-theme giữ lại vì GTK cần nó cho các icon giao diện cơ bản
# (mũi tên, nút) và làm lớp dự phòng khi elementary-xfce thiếu một tên icon.
RUN apt-get update && apt-get install -y --no-install-recommends \
      xfce4-session xfwm4 xfdesktop4 xfce4-panel xfce4-settings \
      xfce4-terminal xfce4-appfinder thunar \
      ristretto mousepad \
      dbus-x11 xdg-utils \
      adwaita-icon-theme \
      elementary-xfce-icon-theme greybird-gtk-theme \
    && rm -rf /var/lib/apt/lists/*

# --- Lớp 4.6: ứng dụng trên desktop ------------------------------------------
# Logo thật cho shortcut desktop (Chromium + VS Code): người dùng nhìn icon
# là biết đây là trình duyệt/editor nào — minh bạch cho computer use.
COPY assets/icons/chromium.png /usr/share/pixmaps/boxfox-chromium.png
COPY assets/icons/vscode.png /usr/share/pixmaps/boxfox-vscode.png
# Chromium của Playwright không nằm trong PATH và không có .desktop nên desktop
# không thấy nó → bọc lại thành một lệnh, rồi tạo entry cho menu/taskbar.
# Đường dẫn giải bằng glob lúc chạy: phiên bản Chromium do bản Playwright đã
# ghim quyết định, không hardcode số hiệu build vào đây.
RUN printf '%s\n' \
      '#!/bin/sh' \
      '# Chromium do Playwright quản lý — chạy như một ứng dụng bình thường trên desktop.' \
      'set -eu' \
      'BIN=$(ls -d /opt/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)' \
      '[ -n "$BIN" ] || { echo "khong tim thay Chromium trong /opt/ms-playwright" >&2; exit 1; }' \
      '# CDP :9222 cho capture/record tab (screen-capture.md). Phải có --user-data-dir' \
      '# riêng để desktop Chromium và box-code (VS Code web) KHÔNG dùng chung profile' \
      '# (nếu chung, box-code sẽ tham gia đúng tiến trình này và giành port 9222).' \
      '# --remote-allow-origins=* để Chromium 111+ không từ chối WebSocket CDP.' \
      'exec "$BIN" --no-sandbox --disable-gpu --disable-dev-shm-usage \' \
      '  --remote-debugging-port=9222 --remote-allow-origins=* \' \
      '  --user-data-dir=/home/agent/.config/box-chromium "$@"' \
      > /usr/local/bin/box-chromium \
    && chmod +x /usr/local/bin/box-chromium \
    && printf '%s\n' \
      '[Desktop Entry]' \
      'Version=1.0' \
      'Type=Application' \
      'Name=Chromium' \
      'Comment=Trình duyệt agent dùng để đọc và thao tác web' \
      'Exec=box-chromium %U' \
      'Icon=/usr/share/pixmaps/boxfox-chromium.png' \
      'Terminal=false' \
      'Categories=Network;WebBrowser;' \
      > /usr/share/applications/chromium-playwright.desktop

# Editor NGAY TRÊN desktop của box, mà vẫn là code-server: mở Chromium ở chế độ
# --app (không thanh địa chỉ, không tab) trỏ vào :8081 (qua proxy). Nhờ vậy người dùng vào
# bằng máy ảo chỉ cần bấm một icon, không phải mở trình duyệt rồi gõ địa chỉ
# localhost. Cùng một tiến trình code-server mà tab IDE của web UI đang dùng —
# một editor, một workspace, không có bản Electron thứ hai.
RUN printf '%s\n' \
      '#!/bin/sh' \
      '# VS Code (bản web) chạy trong box — chỉ là code-server :8080 mở ở chế độ app.' \
      'set -eu' \
      'BIN=$(ls -d /opt/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)' \
      '[ -n "$BIN" ] || { echo "khong tim thay Chromium trong /opt/ms-playwright" >&2; exit 1; }' \
      '# Gọi THẲNG binary, KHÔNG qua box-chromium (box-chromium đã giành port 9222 cho' \
      '# CDP capture). Dùng --user-data-dir riêng để không tham gia singleton desktop.' \
      'exec "$BIN" --no-sandbox --disable-gpu --disable-dev-shm-usage \' \
      '  --user-data-dir=/home/agent/.config/box-code \' \
      '  --app="http://localhost:8081/?folder=/home/agent/workspace" "$@"' \
      > /usr/local/bin/box-code \
    && chmod +x /usr/local/bin/box-code \
    && printf '%s\n' \
      '[Desktop Entry]' \
      'Version=1.0' \
      'Type=Application' \
      'Name=VS Code (Web)' \
      'Comment=code-server trên :8080 — cùng editor với tab IDE của giao diện web' \
      'Exec=box-code' \
      'Icon=/usr/share/pixmaps/boxfox-vscode.png' \
      'Terminal=false' \
      'Categories=Development;IDE;' \
      > /usr/share/applications/box-code.desktop

# --- Lớp 4.7: cầu nối Terminal ------------------------------------------------
# aiohttp ở lớp riêng để không phá cache của các lớp nặng khi chỉnh bridge.
RUN apt-get update && apt-get install -y --no-install-recommends python3-aiohttp \
    && rm -rf /var/lib/apt/lists/*
COPY tty-bridge.py /usr/local/bin/tty-bridge.py
COPY box-services.sh /usr/local/bin/box-services.sh
COPY box-power /usr/local/sbin/box-power
RUN chmod +x /usr/local/bin/tty-bridge.py /usr/local/bin/box-services.sh /usr/local/sbin/box-power

# --- Lớp 5: công tắc mạng + proxy bảo vệ + workspace + entrypoint -------------
COPY box-entrypoint.sh /usr/local/bin/box-entrypoint.sh
COPY box-firewall /usr/local/sbin/box-firewall
COPY ide-proxy.py /usr/local/bin/ide-proxy.py
COPY plan_files.py /usr/local/bin/plan_files.py
COPY capture.py /usr/local/bin/capture.py
COPY browser_capture.py /usr/local/bin/browser_capture.py
COPY bootstrap-plans/ /opt/agentbox/bootstrap-plans/
RUN chmod +x /usr/local/bin/ide-proxy.py /usr/local/bin/capture.py /usr/local/bin/browser_capture.py
# Proxy chèn frame-ancestors vào response của code-server để chặn clickjacking.
# Chỉ origin của giao diện BoxFox (localhost:3100) được nhúng editor vào iframe.
EXPOSE 8081
RUN chmod +x /usr/local/bin/box-entrypoint.sh /usr/local/sbin/box-firewall \
    && mkdir -p /home/agent/workspace /home/agent/.code-server /home/agent/Desktop \
         /home/agent/.vnc /home/agent/.config/xfconf/xfce-perchannel-xml \
    # Icon sẵn trên desktop: mở máy ra là bấm chạy được, không phải đi tìm menu.
    # CHỦ Ý chỉ 3 ứng dụng (+ Home và workspace do xfdesktop/symlink lo): desktop
    # trong khung ④ nhỏ, nhồi thêm Thunar/Filesystem/Trash chỉ làm rối — Home đã
    # mở Thunar, workspace là chỗ agent làm việc.
    && for app in box-code chromium-playwright xfce4-terminal; do \
         cp "/usr/share/applications/${app}.desktop" /home/agent/Desktop/ 2>/dev/null || true; \
       done \
    && chmod +x /home/agent/Desktop/*.desktop \
    # Thư mục workspace hiện luôn trên desktop cho dễ thấy.
    && ln -sfn /home/agent/workspace /home/agent/Desktop/workspace \
    && chown -R agent:agent /home/agent

# --- Lớp 5.5: giao diện desktop (theme tối + icon thật + taskbar 1 thanh) -----
# Đặt Ở CUỐI, sau `chown -R agent:agent /home/agent`, và COPY thẳng với
# --chown=agent:agent — sửa giao diện là việc sẽ làm nhiều lần, để ở đây thì mỗi
# lần chỉnh chỉ rebuild một lớp vài KB thay vì kéo lại Chromium.
#
# Ghi vào HAI chỗ, có chủ ý — để một bản clone sạch trên máy mới lên đúng giao
# diện dù môi trường có lệch:
#   1. /home/agent/.config/...  : cấu hình của người dùng `agent`, ưu tiên cao
#      nhất, và là chỗ xfconfd GHI LẠI khi ai đó đổi cài đặt trong máy.
#   2. /etc/xdg/xfce4/xfconf/...: mặc định toàn hệ thống. Đây là lưới an toàn:
#      nếu HOME bị lệch (gosu không đổi HOME — xem box-services.sh) thì xfconfd
#      vẫn đọc được từ đây. Đã kiểm: không có file ở đây thì xfce4-panel âm thầm
#      rơi về /etc/xdg/xfce4/panel/default.xml (hai thanh, có thanh trắng).
#      Ghi đè xsettings.xml của greybird-gtk-theme là CÓ Ý: file đó đặt
#      ThemeName=Greybird (bản SÁNG), đúng thứ ta cần thay bằng Greybird-dark.
COPY --chown=agent:agent assets/xfconf/ /home/agent/.config/xfconf/xfce-perchannel-xml/
COPY assets/xfconf/ /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/

# Giao diện editor. Đường dẫn phải khớp `--user-data-dir /home/agent/.code-server`
# trong box-services.sh — code-server đọc <user-data-dir>/User/settings.json.
# Lý do từng dòng cấu hình nằm trong chính file settings.json.
COPY --chown=agent:agent assets/code-server/settings.json /home/agent/.code-server/User/settings.json

USER agent
WORKDIR /home/agent/workspace
EXPOSE 5900 6080 8080
ENTRYPOINT ["box-entrypoint.sh"]
