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
  $('groups').textContent = status.groups.join('、');
  const ready = status.running && status.target_group_readable;
  $('status-pill').textContent = status.running ? (ready ? '正在监听' : (status.wechat_window_visible ? '无法核实 @' : '微信已隐藏')) : '已停止';
  $('status-pill').classList.toggle('running', ready);
  $('state-dot').classList.toggle('running', ready);
  $('state-text').textContent = status.running ? (ready ? '助手正在监听' : '助手已暂停监听') : '助手目前未运行';
  $('state-sub').textContent = !status.wechat_window_visible
    ? '请从托盘恢复微信，并打开回复群聊'
    : status.running && !ready
      ? `请在微信主窗口打开 ${status.groups.join('、')} 群并显示左侧会话列表；恢复后只处理新消息`
      : status.running ? `进程 PID ${status.pid} · 只处理真实 @` : '启动由你手动控制';
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
request('/api/status').then(status => render(status, true)).catch(error => notify(error.message, true));
setInterval(() => request('/api/status').then(status => render(status)).catch(() => {}), 10000);
