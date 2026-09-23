const token = document.querySelector('meta[name="control-token"]').content;
const $ = (id) => document.getElementById(id);
let current = null;

function notify(message, error = false) {
  const box = $('notice');
  box.textContent = message;
  box.classList.toggle('error', error);
  box.hidden = false;
}

async function request(path, payload) {
  const options = payload === undefined ? {} : {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Control-Token': token},
    body: JSON.stringify(payload),
  };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}

function render(status, updateForm = false) {
  current = status;
  $('bot-name').textContent = status.bot_name;
  $('account').textContent = status.bot_name;
  $('groups').textContent = status.enabled_groups.join('、') || '无';
  renderGroups(status);
  const multi = status.enabled_groups.length > 1;
  const ready = status.running && (multi ? status.wechat_window_visible : status.target_group_readable);
  $('status-pill').textContent = status.running ? (ready ? (multi ? '轮询进程运行中' : '正在监听') : (status.wechat_window_visible ? '目标群未打开' : '微信已隐藏')) : '已停止';
  $('status-pill').classList.toggle('running', ready);
  $('state-dot').classList.toggle('running', ready);
  $('state-text').textContent = status.running ? (ready ? (multi ? '助手正在尝试逐群扫描' : '助手正在监听') : '助手已暂停监听') : '助手目前未运行';
  $('state-sub').textContent = !status.wechat_window_visible
    ? '请从托盘恢复微信，并打开回复群聊'
    : status.running && !ready
      ? `请在微信打开 ${status.enabled_groups.join('、')} 群；恢复后只处理新消息`
      : status.running ? `进程 PID ${status.pid} · 只处理真实 @${multi ? ' · 群读取失败时会跳过' : ''}` : '启动由你手动控制';
  $('model-status').textContent = status.model_status;
  $('start-btn').disabled = status.running;
  $('stop-btn').disabled = !status.running;
  $('save-model').disabled = status.running;
  if (updateForm) {
    document.querySelector(`input[name="provider"][value="${status.is_local_model ? 'local' : 'api'}"]`).checked = true;
    $('api-url').value = status.is_local_model ? '' : status.api_base_url;
    $('api-model').value = status.is_local_model ? '' : status.model;
    $('api-env').value = status.api_key_env;
    updateProvider();
  }
}

function renderGroups(status) {
  const list = $('group-list');
  list.replaceChildren();
  for (const name of status.groups) {
    const row = document.createElement('div');
    row.className = 'group-row';
    const label = document.createElement('span');
    label.textContent = name;
    const button = document.createElement('button');
    const enabled = status.enabled_groups.includes(name);
    button.type = 'button';
    button.textContent = enabled ? '已启用 · 点击关闭' : '已关闭 · 点击启用';
    button.className = enabled ? 'group-enabled' : 'group-disabled';
    button.disabled = status.running;
    button.addEventListener('click', () => action('/api/groups/enable', {name, enabled: !enabled}, '群设置已保存。'));
    row.append(label, button);
    list.append(row);
  }
  $('group-name').disabled = status.running;
  $('add-group-form').querySelector('button').disabled = status.running;
}

function updateProvider() {
  $('api-fields').hidden = document.querySelector('input[name="provider"]:checked').value !== 'api';
}

async function action(path, payload, success) {
  const buttons = document.querySelectorAll('button');
  buttons.forEach(button => button.disabled = true);
  try {
    const status = await request(path, payload);
    render(status, path === '/api/model');
    notify(success);
  } catch (error) {
    notify(error.message, true);
    if (current) render(current);
  }
}

document.querySelectorAll('input[name="provider"]').forEach(input => input.addEventListener('change', updateProvider));
$('start-btn').addEventListener('click', () => {
  if (!$('accept-focus').checked) return notify('请先勾选焦点提示，再启动助手。', true);
  action('/api/start', {accept_focus: true}, '助手已启动。');
});
$('stop-btn').addEventListener('click', () => action('/api/stop', {}, '助手已停止。'));
$('save-model').addEventListener('click', () => {
  const provider = document.querySelector('input[name="provider"]:checked').value;
  const payload = provider === 'local' ? {provider} : {
    provider, api_base_url: $('api-url').value.trim(), model: $('api-model').value.trim(), api_key_env: $('api-env').value.trim(),
  };
  action('/api/model', payload, '模型设置已保存。');
});
$('add-group-form').addEventListener('submit', event => {
  event.preventDefault();
  const name = $('group-name').value.trim();
  if (!name) return;
  action('/api/groups/add', {name}, '群已添加，默认关闭。');
  $('group-name').value = '';
});
request('/api/status').then(status => render(status, true)).catch(error => notify(error.message, true));
setInterval(() => request('/api/status').then(status => render(status)).catch(() => {}), 10000);
