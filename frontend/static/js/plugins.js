/* Apollodorus 2.0 // Dynamic Plugin Engine & Workbench */

function getPluginCategoryKey(name, desc = '') {
  const n = (name || '').toLowerCase();
  const d = (desc || '').toLowerCase();
  if (n.includes('image') || n.includes('sd_') || d.includes('画') || d.includes('图')) return 'vision';
  if (n.includes('tts') || n.includes('sovits') || d.includes('音') || d.includes('语音')) return 'audio';
  if (n.includes('openai') || n.includes('gpt') || d.includes('llm') || d.includes('模型')) return 'llm';
  if (n.includes('trans') || d.includes('译') || d.includes('翻译')) return 'translate';
  return 'tools';
}

function getPluginCategoryLabel(key) {
  switch (key) {
    case 'vision': return '图像生成 · VISION';
    case 'audio': return '语音合成 · AUDIO/TTS';
    case 'llm': return '大语言模型 · LLM';
    case 'translate': return '语言服务 · TRANSLATE';
    default: return '微服务接口 · SERVICE';
  }
}

function parseExample(code) {
  if (!code) return { method: 'POST', url: '', body: {} };
  const lines = code.trim().split('\n');
  let method = 'POST', url = '', body = {};
  for (const l of lines) {
    const curlM = l.match(/curl\s+-X\s+(\w+)\s+['"]?([^'"]+)['"]?/);
    if (curlM) { method = curlM[1].toUpperCase(); url = curlM[2]; }
    const postM = l.match(/POST\s+(\S+)/);
    if (postM) { method = 'POST'; url = postM[1]; }
    const getM  = l.match(/GET\s+(\S+)/);
    if (getM)  { method = 'GET';  url = getM[1]; }
  }
  const bodyIdx = code.indexOf('{');
  if (bodyIdx !== -1) {
    try {
      let bStr = code.slice(bodyIdx);
      const endIdx = bStr.lastIndexOf('}');
      if (endIdx !== -1) bStr = bStr.slice(0, endIdx + 1);
      body = JSON.parse(bStr);
    } catch (_) {}
  }
  return { method, url, body };
}

/* 首页接口卡（由后端 /api/plugins 自动生成） */
function renderHomeHub() {
  const el = document.getElementById('home-hub');
  if (!el) return;
  if (!S.plugins || !S.plugins.length) {
    el.innerHTML = '<div class="text-muted" style="grid-column:1/-1;text-align:center;padding:48px 0;font-family:var(--font-mono)">[GATEWAY READY] 未发现已注册的插件模块</div>';
    return;
  }

  el.innerHTML = S.plugins.map(p => {
    const catKey = getPluginCategoryKey(p.name, p.description);
    const catLabel = getPluginCategoryLabel(catKey);
    const rpmTag = p.rpm ? `<span class="hub-tag">RPM: ${p.rpm}</span>` : '<span class="hub-tag">RPM: ∞</span>';
    const quotaTag = p.quota_default != null ? `<span class="hub-tag">默认配额: ${p.quota_default}次</span>` : '<span class="hub-tag">默认配额: ∞</span>';
    const pt = p.post_test || {};
    const method = (pt.type || 'POST').toUpperCase();
    const endpoint = pt.end_point || `/api/v1/${p.name}`;

    return `
      <div class="hub-card" data-category="${catKey}" data-search-text="${escHtml(p.name)} ${escHtml(p.display_name||'')} ${escHtml(p.description||'')} ${escHtml(catLabel)} ${escHtml(endpoint)}">
        <div class="hub-card-head">
          <span class="hub-card-cat">${catLabel}</span>
          <div style="display:flex;align-items:center;gap:6px">
            <span class="hub-card-method method-${method.toLowerCase()}">${method}</span>
            <span class="hub-status-dot" title="节点在线运行中"></span>
          </div>
        </div>
        <div class="hub-card-title-row">
          <h3 class="hub-card-title">${escHtml(p.display_name || p.name)}</h3>
          <span class="hub-card-id">${escHtml(p.name)}</span>
        </div>
        <div class="hub-card-endpoint-box">
          <span class="endpoint-text">${escHtml(endpoint)}</span>
          <button class="endpoint-copy-btn" onclick="copyText('${escHtml(endpoint)}', '接口路径已复制')" title="复制路径">📋</button>
        </div>
        <div class="hub-card-desc" title="${escHtml(p.description || '')}">${escHtml(p.description || '统一微服务标准接口，支持高并发流式反代与配额审计。')}</div>
        <div class="hub-card-tags">
          ${rpmTag}
          ${quotaTag}
          <span class="hub-tag tag-healthy"><span class="pulse-dot" style="width:5px;height:5px;margin-right:4px"></span>ONLINE</span>
        </div>
        <div class="hub-card-actions">
          <button class="btn btn-primary btn-sm" onclick="goPage('plugin-${p.name}')">
            <span>在线调试 Workbench</span>
            <span style="font-family:var(--font-mono)">→</span>
          </button>
          <button class="btn btn-secondary btn-sm" onclick="goPage('plugin-${p.name}'); switchPluginTab('${p.name}','docs');">
            <span>集成文档 / cURL</span>
          </button>
        </div>
      </div>
    `;
  }).join('');

  // 触发筛选计数更新
  if (typeof applyHubFilter === 'function') {
    applyHubFilter();
  }
}

/* 动态为每个插件生成完整独立页面 */
function buildPluginPages() {
  document.querySelectorAll('.plugin-generated-page').forEach(el => el.remove());

  const container = document.getElementById('plugin-pages-container') || document.body;
  S.plugins.forEach(p => {
    const pageEl = document.createElement('div');
    pageEl.className = 'page plugin-generated-page';
    pageEl.id = `page-plugin-${p.name}`;
    pageEl.innerHTML = buildPluginPage(p);
    container.appendChild(pageEl);
  });
}

function buildPluginPage(p) {
  const exampleCode = (p.example || '').trim();
  const pt = p.post_test || null;
  let testMethod = 'POST', testUrl = '', testBodyObj = {};
  if (pt) {
    testMethod = (pt.type || 'POST').toUpperCase();
    testUrl = pt.end_point || '';
    testBodyObj = pt.params || {};
  } else {
    const parsed = parseExample(exampleCode);
    testMethod = parsed.method || 'POST';
    testUrl = parsed.url || `/api/v1/${p.name}`;
    testBodyObj = parsed.body || {};
  }
  const testBody = escHtml(JSON.stringify(testBodyObj, null, 2));
  const extraFieldsHtml = pt && pt.params ? buildExtraFields(p.name, pt.params) : '';

  let fileFieldsHtml = '';
  if (pt && Array.isArray(pt.files) && pt.files.length > 0) {
    fileFieldsHtml = `
      <div class="form-group" style="margin-top:14px">
        <label class="form-label" style="display:flex;align-items:center;gap:6px">
          <span style="color:var(--sky-primary)">📁</span>
          <span>文件上传附件 (multipart/form-data)</span>
        </label>
        <div style="display:flex;flex-direction:column;gap:10px;background:var(--bg-subtle);padding:14px;border-radius:var(--radius-sm);border:1px dashed var(--camel-border)">
          ${pt.files.map(fKey => `
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
              <span style="font-family:var(--font-mono);font-size:12px;color:var(--mocha-primary);width:130px;flex-shrink:0;font-weight:600">${escHtml(fKey)}:</span>
              <input type="file" id="tfile-${p.name}-${escHtml(fKey)}" multiple class="form-input" style="flex:1;min-width:200px;padding:6px 10px;font-size:12px;background:#fff" />
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  // API Key selector options
  const keyOptions = (S.userKeys || []).map(k => `
    <option value="${escHtml(k.name)}">${escHtml(k.name)} (${escHtml(k.key_prefix)}…)</option>
  `).join('');

  return `
    <div style="margin-bottom:24px">
      <div style="display:flex;align-items:center;gap:8px;font-family:var(--font-mono);font-size:12px;color:var(--text-tertiary);margin-bottom:8px">
        <span onclick="goPage('home')" style="cursor:pointer;color:var(--mocha-primary);font-weight:600">← 返回接口市场</span>
        <span>/</span>
        <span style="color:var(--sky-primary)">${escHtml(p.name)}</span>
      </div>
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px">
        <div>
          <h1 style="font-size:24px;font-weight:700;letter-spacing:-0.02em;margin-bottom:6px;color:var(--mocha-dark)">${escHtml(p.display_name || p.name)}</h1>
          <p style="color:var(--text-secondary);font-size:14px;max-width:700px">${escHtml(p.description || '高性能统一微服务网关接口')}</p>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          ${p.rpm ? `<span class="tag tag-amber">RPM: ${p.rpm}</span>` : '<span class="tag tag-amber">RPM: ∞</span>'}
          ${p.quota_default != null ? `<span class="tag tag-teal">默认配额: ${p.quota_default}次</span>` : '<span class="tag tag-green">无限配额</span>'}
          <span class="tag tag-cyan">${testMethod}</span>
        </div>
      </div>
    </div>

    <!-- 选项卡切换 -->
    <div class="tabs" style="margin-bottom:24px">
      <div class="tab-btn active" id="tab-btn-${p.name}-wb" onclick="switchPluginTab('${p.name}', 'wb')">
        <span>⚡ 交互式调试 Workbench</span>
      </div>
      <div class="tab-btn" id="tab-btn-${p.name}-docs" onclick="switchPluginTab('${p.name}', 'docs')">
        <span>📖 接口规范与代码集成 Docs</span>
      </div>
    </div>

    <!-- TAB 1: WORKBENCH -->
    <div id="tab-panel-${p.name}-wb" class="tab-panel" style="display:block">
      <div class="workbench-grid">
        <!-- 左侧：参数配置 -->
        <div class="card" style="margin-bottom:0">
          <div class="card-head">
            <span class="card-title">请求配置 Request Inspector</span>
            <span style="font-family:var(--font-mono);font-size:11px;color:var(--sky-primary);background:var(--sky-light);padding:2px 8px;border-radius:4px">${testMethod} ${escHtml(testUrl)}</span>
          </div>

          <div style="padding:18px 20px">
            <!-- 凭证选择 -->
            <div class="form-group">
              <label class="form-label" style="display:flex;align-items:center;justify-content:space-between">
                <span>鉴权密钥 Authorization</span>
                <span style="font-size:11px;color:var(--text-tertiary);cursor:pointer;color:var(--mocha-primary)" onclick="goPage('apikeys')">🔑 管理 API 密钥 →</span>
              </label>
              <div style="display:flex;gap:8px">
                <select id="tkey-sel-${p.name}" class="form-input" style="flex:1" onchange="onKeySelectChange('${p.name}')">
                  <option value="">自动使用当前用户登录 Token</option>
                  ${keyOptions}
                  <option value="custom">输入自定义 Bearer Key...</option>
                </select>
                <input type="text" id="tkey-${p.name}" class="form-input" placeholder="Bearer sk-..." style="flex:1;display:none;font-family:var(--font-mono);font-size:12px" />
              </div>
            </div>

            <!-- 可视化参数表单 -->
            ${extraFieldsHtml ? `
              <div style="margin-top:14px;border-top:1px solid var(--border-dim);padding-top:14px">
                <div style="font-size:11.5px;font-weight:600;color:var(--text-secondary);margin-bottom:10px">表单参数直调 (FIELDS MAPPER)</div>
                ${extraFieldsHtml}
              </div>
            ` : ''}

            <!-- 文件上传 (若有) -->
            ${fileFieldsHtml}

            <!-- 原始请求报文 JSON 编辑区 -->
            <div class="form-group" style="margin-top:14px">
              <label class="form-label" style="display:flex;align-items:center;justify-content:space-between">
                <span>Payload JSON 编辑器</span>
                <span style="font-size:11px;color:var(--text-tertiary)">支持手动调整参数报文</span>
              </label>
              <textarea id="tbody-${p.name}" class="form-input" rows="8" style="font-family:var(--font-mono);font-size:12px;line-height:1.5">${testBody}</textarea>
            </div>

            <button class="btn btn-primary" id="tbtn-${p.name}" style="width:100%;padding:12px;margin-top:8px" onclick="runTest('${p.name}')">
              <span id="tbtn-txt-${p.name}">⚡ 发送测试请求 (EXECUTE)</span>
            </button>
          </div>
        </div>

        <!-- 右侧：响应状态与结果 -->
        <div class="card" style="margin-bottom:0;display:flex;flex-direction:column">
          <div class="card-head">
            <span class="card-title">实时响应 Live Inspector</span>
            <div style="display:flex;align-items:center;gap:10px">
              <span id="tlatency-${p.name}" style="font-family:var(--font-mono);font-size:11.5px;color:var(--text-tertiary)"></span>
              <span id="tstatus-${p.name}"><span class="tag tag-slate">READY</span></span>
            </div>
          </div>

          <div style="padding:18px 20px;flex:1;display:flex;flex-direction:column">
            <!-- 媒体预览槽位 (自动探测图片或音频) -->
            <div id="tmedia-${p.name}" style="display:none;margin-bottom:16px"></div>

            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
              <span style="font-size:11px;font-family:var(--font-mono);color:var(--text-tertiary)">RESPONSE BODY (JSON / TEXT)</span>
              <span class="btn-copy" onclick="copyCode('tout-${p.name}')">复制响应</span>
            </div>
            <pre id="tout-${p.name}" class="test-result-wrap" style="flex:1;min-height:280px;margin:0;font-size:12px;color:var(--text-secondary);background:var(--bg-subtle)">// 点击 "发送测试请求" 查看后端返回结果...</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 2: DOCS & INTEGRATION -->
    <div id="tab-panel-${p.name}-docs" class="tab-panel" style="display:none">
      <div class="card">
        <div class="card-head">
          <span class="card-title">cURL 快速调用命令</span>
          <span class="btn-copy" onclick="copyCode('code-curl-${p.name}')">复制 cURL</span>
        </div>
        <div style="padding:18px 20px">
          <pre class="code-block" id="code-curl-${p.name}">curl -X ${testMethod} "${location.origin}${testUrl}" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '${JSON.stringify(testBodyObj, null, 2)}'</pre>
        </div>
      </div>

      <div class="card" style="margin-top:20px">
        <div class="card-head">
          <span class="card-title">Python (requests) 接入示例</span>
          <span class="btn-copy" onclick="copyCode('code-py-${p.name}')">复制 Python</span>
        </div>
        <div style="padding:18px 20px">
          <pre class="code-block" id="code-py-${p.name}">import requests

url = "${location.origin}${testUrl}"
headers = {
    "Authorization": "Bearer YOUR_API_KEY",
    "Content-Type": "application/json"
}
payload = ${JSON.stringify(testBodyObj, null, 4)}

response = requests.${testMethod.toLowerCase()}(url, json=payload, headers=headers)
print("Status:", response.status_code)
print(response.json())</pre>
        </div>
      </div>

      <div class="card" style="margin-top:20px">
        <div class="card-head">
          <span class="card-title">JavaScript (fetch) 接入示例</span>
          <span class="btn-copy" onclick="copyCode('code-js-${p.name}')">复制 JavaScript</span>
        </div>
        <div style="padding:18px 20px">
          <pre class="code-block" id="code-js-${p.name}">const res = await fetch("${location.origin}${testUrl}", {
  method: "${testMethod}",
  headers: {
    "Authorization": "Bearer YOUR_API_KEY",
    "Content-Type": "application/json"
  },
  body: JSON.stringify(${JSON.stringify(testBodyObj, null, 2)})
});
const data = await res.json();
console.log(data);</pre>
        </div>
      </div>
    </div>
  `;
}

function buildExtraFields(pluginName, params) {
  return Object.entries(params).map(([key, val]) => {
    const isBool = typeof val === 'boolean';
    const isNum = typeof val === 'number';
    const isObj = typeof val === 'object' && val !== null;
    const inputType = isNum ? 'number' : 'text';

    if (isBool) {
      return `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
          <span style="font-family:var(--font-mono);font-size:12px;color:var(--text-secondary)">${escHtml(key)}</span>
          <label style="display:inline-flex;align-items:center;cursor:pointer">
            <input type="checkbox" id="field-${pluginName}-${key}" ${val ? 'checked' : ''} onchange="syncFieldToPayload('${pluginName}', '${key}', this.checked)" style="accent-color:var(--mocha-primary)" />
          </label>
        </div>
      `;
    }

    if (isObj) {
      return `
        <div style="margin-bottom:10px">
          <label class="form-label" style="font-size:11px">${escHtml(key)} (JSON)</label>
          <textarea id="field-${pluginName}-${key}" class="form-input" rows="2" style="font-family:var(--font-mono);font-size:11.5px" oninput="syncFieldToPayload('${pluginName}', '${key}', this.value, true)">${escHtml(JSON.stringify(val))}</textarea>
        </div>
      `;
    }

    return `
      <div style="margin-bottom:10px">
        <label class="form-label" style="font-size:11px">${escHtml(key)}</label>
        <input type="${inputType}" id="field-${pluginName}-${key}" class="form-input" value="${escHtml(val)}" style="font-family:var(--font-mono);font-size:12px" oninput="syncFieldToPayload('${pluginName}', '${key}', this.value, false, ${isNum})" />
      </div>
    `;
  }).join('');
}

function syncFieldToPayload(pluginName, key, value, isJson = false, isNum = false) {
  const ta = document.getElementById(`tbody-${pluginName}`);
  if (!ta) return;
  try {
    const current = JSON.parse(ta.value || '{}');
    if (isJson) {
      try { current[key] = JSON.parse(value); } catch(_) { current[key] = value; }
    } else if (isNum) {
      current[key] = Number(value);
    } else {
      current[key] = value;
    }
    ta.value = JSON.stringify(current, null, 2);
  } catch(_) {}
}

function switchPluginTab(pluginName, tab) {
  ['wb', 'docs'].forEach(t => {
    const btn = document.getElementById(`tab-btn-${pluginName}-${t}`);
    const panel = document.getElementById(`tab-panel-${pluginName}-${t}`);
    if (btn) btn.classList.toggle('active', t === tab);
    if (panel) panel.style.display = (t === tab) ? 'block' : 'none';
  });
}

function onKeySelectChange(pluginName) {
  const sel = document.getElementById(`tkey-sel-${pluginName}`);
  const inp = document.getElementById(`tkey-${pluginName}`);
  if (!sel || !inp) return;
  if (sel.value === 'custom') {
    inp.style.display = 'block';
    inp.value = '';
    inp.focus();
  } else {
    inp.style.display = 'none';
    inp.value = '';
  }
}

/* 执行在线测试 */
async function runTest(pluginName) {
  const p = S.plugins.find(x => x.name === pluginName);
  if (!p) return;

  const pt = p.post_test || {};
  const method = (pt.type || 'POST').toUpperCase();
  const endpoint = pt.end_point || `/api/v1/${p.name}`;

  const btn = document.getElementById(`tbtn-${pluginName}`);
  const btnTxt = document.getElementById(`tbtn-txt-${pluginName}`);
  const statusEl = document.getElementById(`tstatus-${pluginName}`);
  const latencyEl = document.getElementById(`tlatency-${pluginName}`);
  const outEl = document.getElementById(`tout-${pluginName}`);
  const mediaEl = document.getElementById(`tmedia-${pluginName}`);

  if (btn) btn.disabled = true;
  if (btnTxt) btnTxt.innerHTML = '<span class="test-spinner"></span> 执行请求中...';
  if (statusEl) statusEl.innerHTML = '<span class="tag tag-amber">REQUESTING</span>';
  if (latencyEl) latencyEl.textContent = '...';
  if (mediaEl) { mediaEl.style.display = 'none'; mediaEl.innerHTML = ''; }
  if (outEl) outEl.textContent = '正在等待网关节点响应...';

  const tStart = performance.now();

  try {
    let headers = {};
    const selKey = document.getElementById(`tkey-sel-${pluginName}`)?.value;
    const customKey = (document.getElementById(`tkey-${pluginName}`)?.value || '').trim();

    if (selKey === 'custom' && customKey) {
      headers['Authorization'] = customKey.startsWith('Bearer ') ? customKey : `Bearer ${customKey}`;
    } else if (selKey && selKey !== 'custom') {
      const matchKey = (S.userKeys || []).find(k => k.name === selKey);
      if (matchKey && S.token) {
        headers['Authorization'] = `Bearer ${S.token}`;
      } else if (S.token) {
        headers['Authorization'] = `Bearer ${S.token}`;
      }
    } else if (S.token) {
      headers['Authorization'] = `Bearer ${S.token}`;
    }

    let reqBody = null;
    let hasFiles = false;
    const formData = new FormData();

    // Check files
    if (pt.files && Array.isArray(pt.files)) {
      pt.files.forEach(fKey => {
        const finp = document.getElementById(`tfile-${pluginName}-${fKey}`);
        if (finp && finp.files && finp.files.length > 0) {
          hasFiles = true;
          for (let i = 0; i < finp.files.length; i++) {
            formData.append(fKey, finp.files[i]);
          }
        }
      });
    }

    const bodyText = (document.getElementById(`tbody-${pluginName}`)?.value || '').trim();

    if (hasFiles) {
      if (bodyText) {
        try {
          const parsed = JSON.parse(bodyText);
          Object.entries(parsed).forEach(([k, v]) => {
            formData.append(k, typeof v === 'object' ? JSON.stringify(v) : v);
          });
        } catch (_) {}
      }
      reqBody = formData;
    } else if (method !== 'GET' && method !== 'HEAD') {
      headers['Content-Type'] = 'application/json';
      reqBody = bodyText || '{}';
    }

    const res = await fetch(API + endpoint, {
      method,
      headers,
      body: reqBody
    });

    const elapsed = Math.round(performance.now() - tStart);
    if (latencyEl) latencyEl.textContent = `${elapsed} ms`;
    if (statusEl) statusEl.innerHTML = statusTag(res.status);

    const contentType = res.headers.get('content-type') || '';

    // Handle Audio stream response
    if (contentType.includes('audio') || contentType.includes('octet-stream')) {
      const blob = await res.blob();
      const audioUrl = URL.createObjectURL(blob);
      if (mediaEl) {
        mediaEl.style.display = 'block';
        mediaEl.innerHTML = `
          <div class="test-audio-wrap">
            <div style="font-size:12px;font-family:var(--font-mono);color:var(--sage-primary);margin-bottom:8px;font-weight:600">⚡ 音频流检测就绪 · 可直接在线试听</div>
            <audio controls src="${audioUrl}" autoplay style="width:100%"></audio>
          </div>
        `;
      }
      if (outEl) outEl.textContent = `[Binary Audio Stream / ${blob.size} bytes / Content-Type: ${contentType}]`;
      return;
    }

    // Handle JSON or Text
    const textData = await res.text();
    let jsonData = null;
    try { jsonData = JSON.parse(textData); } catch (_) {}

    if (jsonData) {
      if (outEl) outEl.textContent = JSON.stringify(jsonData, null, 2);

      // Inspect for Image generation results
      let images = [];
      if (Array.isArray(jsonData.data)) {
        jsonData.data.forEach(item => {
          if (item.url) images.push(item.url);
          else if (item.b64_json) images.push(`data:image/png;base64,${item.b64_json}`);
        });
      } else if (jsonData.image_url) {
        images.push(jsonData.image_url);
      } else if (jsonData.url && typeof jsonData.url === 'string' && (jsonData.url.startsWith('http') || jsonData.url.startsWith('data:image'))) {
        images.push(jsonData.url);
      }

      if (images.length && mediaEl) {
        mediaEl.style.display = 'block';
        mediaEl.innerHTML = `
          <div style="font-size:12px;font-family:var(--font-mono);color:var(--sky-primary);margin-bottom:10px;font-weight:600">🖼 检测到生成的图像渲染结果 (${images.length} 张):</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(180px, 1fr));gap:12px">
            ${images.map(img => `
              <div style="border:1px solid var(--border-default);border-radius:var(--radius-sm);overflow:hidden;background:#fff;box-shadow:var(--shadow-sm)">
                <a href="${img}" target="_blank" rel="noopener">
                  <img src="${img}" style="width:100%;height:160px;object-fit:cover;display:block" alt="generated" />
                </a>
              </div>
            `).join('')}
          </div>
        `;
      }

      // Inspect for Audio result inside JSON
      if (jsonData.audio_url && mediaEl) {
        mediaEl.style.display = 'block';
        mediaEl.innerHTML = `
          <div class="test-audio-wrap">
            <div style="font-size:12px;font-family:var(--font-mono);color:var(--sage-primary);margin-bottom:8px;font-weight:600">⚡ 检测到生成的语音直链:</div>
            <audio controls src="${jsonData.audio_url}" autoplay style="width:100%"></audio>
          </div>
        `;
      }
    } else {
      if (outEl) outEl.textContent = textData || '[Empty Response]';
    }

  } catch (err) {
    const elapsed = Math.round(performance.now() - tStart);
    if (latencyEl) latencyEl.textContent = `${elapsed} ms`;
    if (statusEl) statusEl.innerHTML = '<span class="tag tag-red">NET ERR</span>';
    if (outEl) outEl.textContent = `请求网络故障: ${err.message}`;
  } finally {
    if (btn) btn.disabled = false;
    if (btnTxt) btnTxt.innerHTML = '⚡ 发送测试请求 (EXECUTE)';
  }
}
