#!/usr/bin/env bash
# Parameters are paths/versions only. Credentials arrive in a private SFTP file.
set -euo pipefail
umask 077
workspace=$1
binary=$2
node_version=$3
opencode_version=$4
npm_registry=$5
payload=$6
operation=$7
cache="$HOME/.cache/astra-provision"
mkdir -p "$cache"
exec 9>"$cache/install.lock"
flock -n 9 || { echo '同一 SSH 用户已有部署操作，请等待远端操作结束后重试' >&2; exit 75; }
step() { printf 'ASTRA_STEP\t%s\t%s\n' "$1" "$2"; }
download() { curl --fail --location --silent --show-error --connect-timeout 15 --max-time 180 --retry 2 "$1" -o "$2"; }
trap 'rm -f "$payload"' EXIT
step '系统依赖' running
test "$(uname -s)" = Linux || { echo '只支持 Linux' >&2; exit 1; }
case "$(uname -m)" in x86_64) arch=x64 ;; aarch64) arch=arm64 ;; *) echo '只支持 x86_64 / aarch64' >&2; exit 1 ;; esac
. /etc/os-release
old_glibc=false
glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}' || true)
if test -n "$glibc" && test "$(printf '2.28\n%s\n' "$glibc" | sort -V | head -1)" != 2.28; then old_glibc=true; fi
if test "$old_glibc" = true && test "$arch" != x64; then echo '旧 glibc 仅支持 x86_64，请升级系统' >&2; exit 1; fi
python_bin=${8:-python3}
if ! "$python_bin" -c 'import sys; sys.exit(sys.version_info<(3,11))' >/dev/null 2>&1; then
  echo '需要 Python ≥3.11' >&2
  exit 1
fi
py_mm=$("$python_bin" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
venv_pkg="python${py_mm}-venv"
install_venv=false
if ! "$python_bin" -c 'import ensurepip' >/dev/null 2>&1; then install_venv=true; fi
if test "$(id -u)" = 0; then
  if command -v apt-get >/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl tar xz-utils unzip git build-essential libcurl4-openssl-dev libssl-dev libexpat1-dev zlib1g-dev gettext
    if test "$install_venv" = true; then apt-get install -y -qq "$venv_pkg" || apt-get install -y -qq python3-venv; fi
  elif command -v yum >/dev/null; then
    yum_args=()
    if test "$ID" = centos && test "${VERSION_ID%%.*}" = 7; then
      mkdir -p "$cache/repos"
      cat >"$cache/repos/centos-vault.repo" <<'REPO'
[astra-vault-base]
name=CentOS 7 archive base
baseurl=https://vault.centos.org/7.9.2009/os/$basearch/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7
enabled=1
[astra-vault-updates]
name=CentOS 7 archive updates
baseurl=https://vault.centos.org/7.9.2009/updates/$basearch/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7
enabled=1
REPO
      yum_args=(--setopt="reposdir=$cache/repos")
    fi
    yum "${yum_args[@]}" -y -q install ca-certificates curl tar xz unzip git gcc gcc-c++ make libcurl-devel openssl-devel expat-devel zlib-devel gettext-devel perl-ExtUtils-MakeMaker
  else echo '不支持的系统包管理器，需要 Debian/Ubuntu 或 RHEL 系列' >&2; exit 1; fi
else
  for tool in curl tar xz git flock; do command -v "$tool" >/dev/null || { echo "缺少 $tool，请管理员安装系统依赖" >&2; exit 1; }; done
fi
if ! "$python_bin" -c 'import ensurepip' >/dev/null 2>&1; then echo "需要安装 $venv_pkg" >&2; exit 1; fi
step '系统依赖' passed
step 'Node.js 与 npm 镜像' running
node_dist=linux-$arch
node_source=https://nodejs.org/dist
if test "$old_glibc" = true; then node_dist=linux-x64-glibc-217; node_source=https://unofficial-builds.nodejs.org/download/release; fi
node_root="$HOME/.local/share/astra/node-v$node_version"
if ! test -x "$node_root/bin/node" || ! "$node_root/bin/node" --version >/dev/null 2>&1; then
  archive="node-v$node_version-$node_dist.tar.xz"
  download "$node_source/v$node_version/$archive" "$cache/$archive"
  download "$node_source/v$node_version/SHASUMS256.txt" "$cache/node-sha256.txt"
  (cd "$cache"; awk -v file="$archive" '$2 == file { print; found=1 } END { if (!found) exit 1 }' node-sha256.txt | sha256sum -c -)
  mkdir -p "$node_root"
  tar -xJf "$cache/$archive" -C "$node_root" --strip-components=1
fi
export PATH="$node_root/bin:/usr/local/bin:$PATH"
node --version
npm config set registry "$npm_registry" --location=user
npm config get registry
if test "$(id -u)" = 0; then
  for tool in node npm npx; do ln -sfn "$node_root/bin/$tool" "/usr/local/bin/$tool"; done
else
  mkdir -p "$HOME/.local/bin"
  for tool in node npm npx; do ln -sfn "$node_root/bin/$tool" "$HOME/.local/bin/$tool"; done
fi
step 'Node.js 与 npm 镜像' passed
step 'Git 工作树' running
git_version=$(git version | awk '{print $3}')
if test "$(printf '2.20.0\n%s\n' "$git_version" | sort -V | head -1)" != 2.20.0; then
  test "$(id -u)" = 0 || { echo 'Git 版本低于 2.20，请管理员升级' >&2; exit 1; }
  # The maintained 2.43 line supports CentOS 7's libcurl/OpenSSL headers.
  git_release=2.43.7
  archive="git-$git_release.tar.xz"
  download "https://www.kernel.org/pub/software/scm/git/$archive" "$cache/$archive"
  download 'https://www.kernel.org/pub/software/scm/git/sha256sums.asc' "$cache/git-sha256.txt"
  (cd "$cache"; awk -v file="$archive" '$2 == file { print; found=1 } END { if (!found) exit 1 }' git-sha256.txt | sha256sum -c -)
  tar -xJf "$cache/$archive" -C "$cache"
  git_flags=()
  if test "$old_glibc" = true; then git_flags=(CSPRNG_METHOD=openssl); fi
  make -s -C "$cache/git-$git_release" -j2 prefix=/usr/local NO_TCLTK=YesPlease NO_GETTEXT=YesPlease "${git_flags[@]}" all install
fi
git version
step 'Git 工作树' passed
step 'OpenCode 安装' running
if test "$old_glibc" = true; then
  test "$(id -u)" = 0 || { echo '旧 glibc 需要管理员安装 musl 运行库' >&2; exit 1; }
  musl_root="$HOME/.local/share/astra/musl-runtime"
  if ! test -x "$musl_root/sbin/apk"; then
    alpine_archive=alpine-minirootfs-3.22.6-x86_64.tar.gz
    alpine_url=https://dl-cdn.alpinelinux.org/alpine/v3.22/releases/x86_64
    download "$alpine_url/$alpine_archive" "$cache/$alpine_archive"
    download "$alpine_url/$alpine_archive.sha256" "$cache/alpine-sha256.txt"
    (cd "$cache"; sha256sum -c alpine-sha256.txt)
    mkdir -p "$musl_root"
    tar -xzf "$cache/$alpine_archive" -C "$musl_root"
  fi
  # apk verifies repository/package signatures with the official rootfs keys.
  SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt "$musl_root/lib/ld-musl-x86_64.so.1" \
    --library-path "$musl_root/lib:$musl_root/usr/lib" "$musl_root/sbin/apk" \
    --root "$musl_root" --keys-dir "$musl_root/etc/apk/keys" \
    --repositories-file "$musl_root/etc/apk/repositories" --no-scripts add libgcc libstdc++
  if ! test -e /lib/ld-musl-x86_64.so.1; then ln -s "$musl_root/lib/ld-musl-x86_64.so.1" /lib/ld-musl-x86_64.so.1; fi
  # Only musl's loader reads this file; glibc/Node/Git paths stay untouched.
  musl_paths=/etc/ld-musl-x86_64.path
  if ! grep -Fq "$musl_root/usr/lib" "$musl_paths" 2>/dev/null; then
    test -e "$musl_paths" || printf '%s\n' /lib:/usr/local/lib:/usr/lib >"$musl_paths"
    printf '\n%s\n' "$musl_root/lib:$musl_root/usr/lib" >>"$musl_paths"
  fi
fi
# Keep npm's installation independent of the selected Node.js release directory.
npm_prefix="$HOME/.local/share/astra/npm"
npm_binary="$npm_prefix/bin/opencode"
npm_package="$npm_prefix/lib/node_modules/opencode-ai/package.json"
installed_version=$(node -e 'try { const p=require(process.argv[1]); process.stdout.write(p.version || "") } catch {}' "$npm_package")
if test "$installed_version" != "$opencode_version" || ! test -x "$npm_binary" || test "$("$npm_binary" --version 2>/dev/null || true)" != "$opencode_version"; then
  npm install --global --prefix "$npm_prefix" --registry "$npm_registry" \
    --include=optional --no-audit --no-fund --fetch-retries=2 --fetch-timeout=120000 \
    "opencode-ai@$opencode_version"
fi
# Validate npm's executable before replacing a previous manually installed binary.
test "$("$npm_binary" --version)" = "$opencode_version" || { echo 'npm 安装的 OpenCode 实际版本与目标版本不符' >&2; exit 1; }
mkdir -p "$(dirname "$binary")"
if test "$binary" != "$npm_binary"; then ln -sfn "$npm_binary" "$binary"; fi
test "$("$binary" --version)" = "$opencode_version" || { echo 'OpenCode 执行路径未指向目标 npm 版本' >&2; exit 1; }
step 'OpenCode 安装' passed
step '工程目录' running
mkdir -p "$workspace"
if ! git -C "$workspace" rev-parse --git-dir >/dev/null 2>&1; then
  if test -n "$(ls -A "$workspace")"; then echo '工程目录不是 Git 仓库且不为空，请先初始化或配置正确的仓库根目录' >&2; exit 1; fi
  git -C "$workspace" init -q
  git -C "$workspace" -c user.name='Astra' -c user.email='astra@localhost' commit -q --allow-empty -m 'chore: initialize employee workspace'
fi
git -C "$workspace" rev-parse --verify HEAD >/dev/null || { echo '工程仓库没有提交，请先创建初始提交' >&2; exit 1; }
step '工程目录' passed
step '全局 OpenCode 配置' running
node - "$payload" "$operation" <<'NODE'
const fs = require('fs'), path = require('path');
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const target = payload.config_path;
fs.mkdirSync(path.dirname(target), { recursive:true, mode:0o700 });
function load(file) {
  const text = fs.readFileSync(file, 'utf8').split('\n').filter(line => !line.trim().startsWith('//')).join('\n');
  let config;
  try { config = JSON.parse(text); } catch { throw Error('全局 OpenCode 配置不是有效 JSON，请人工处理，未覆盖配置'); }
  if (!config || Array.isArray(config) || typeof config !== 'object') throw Error('全局配置必须是 JSON 对象');
  return config;
}
let config = {};
if (fs.existsSync(target)) {
  config = load(target);
  const backup = target + '.astra-backup-' + process.argv[3];
  fs.copyFileSync(target, backup);
  fs.chmodSync(backup, 0o600);
}
config.$schema = 'https://opencode.ai/config.json';
if (payload.provider) config.provider = {...(config.provider || {}), 'astra-gateway': payload.provider};
config.mcp = {...(config.mcp || {}), 'nexus-library': payload.mcp};
for (const item of payload.mcp_refs || []) {
  if (item && item.name && item.url) {
    config.mcp[item.name] = {type: 'remote', url: item.url, enabled: true, oauth: false};
  }
}
config.model = payload.model;
const tmp = target + '.tmp-' + process.argv[3];
fs.writeFileSync(tmp, JSON.stringify(config, null, 2) + '\n', {mode: 0o600});
fs.renameSync(tmp, target);
const skillRoot = path.join(path.dirname(target), 'skill');
for (const skill of payload.skills || []) {
  if (!skill || !skill.name || skill.body == null) continue;
  const dir = path.join(skillRoot, skill.name);
  fs.mkdirSync(dir, {recursive: true, mode: 0o700});
  fs.writeFileSync(path.join(dir, 'SKILL.md'), skill.body, {mode: 0o600});
}
NODE
step '全局 OpenCode 配置' passed
