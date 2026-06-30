/* Apollodorus 前端 — 由 index.html 拆分而来；所有文件共享全局作用域，按 index.html 中的顺序加载。 */
/* ─── PLUGIN PAGE BUILDER ───────────────────────────────────────── */
function buildPluginPage(p) {
  const exampleCode = (p.example || '').trim();
  const pt = p.post_test || null;
  const loggedIn = !!(S.token && S.user);

  let testMethod = 'POST', testUrl = '', testBodyObj = {};
  if (pt) {
    testMethod = (pt.type || 'POST').toUpperCase();
    testUrl    = pt.end_point || '';
    testBodyObj = pt.params || {};
  } else {
    const parsed = parseExample(exampleCode);
    testMethod   = parsed.method || 'POST';
    testUrl      = parsed.url    || '';
    testBodyObj  = parsed.body   || {};
  }
  const testBody = escHtml(JSON.stringify(testBodyObj, null, 2));

  const extraFieldsHtml = pt && pt.params ? buildExtraFields(p.name, pt.params) : '';

  // 渲染带有具体字段名的多文件上传组件
  let fileFieldsHtml = '';
  let hasFiles = false;
  if (pt && Array.isArray(pt.files) && pt.files.length > 0) {
    hasFiles = true;
    fileFieldsHtml = `
      <div>
        <label class="form-label">File Attachments (multipart/form-data)</label>
        <div style="display:flex;flex-direction:column;gap:8px">
          ${pt.files.map(fKey => `
            <div style="display:flex;align-items:center;gap:8px">
              <span style="font-family:var(--mono);font-size:11px;color:var(--text3);width:120px;flex-shrink:0">${escHtml(fKey)}</span>
              <input type="file" id="tfile-${p.name}-${escHtml(fKey)}" multiple class="form-input" style="flex:1;font-family:var(--mono);font-size:12px" data-filekey="${escHtml(fKey)}" />
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  const hasExample = exampleCode.length > 0;
  const exampleHtml = hasExample
    ? `<div class="code-block-wrap">
         <pre class="code-block" id="ex-code-${p.name}">${escHtml(exampleCode)}</pre>
         <button class="code-copy-btn" onclick="copyCode('ex-code-${p.name}')">COPY</button>
       </div>`
    : `<div class="text-muted">No example available for this plugin.</div>`;

  const infoStrip = p.quota_default != null
    ? `<div class="plugin-info-strip">
         <span class="pis-quota">Daily Quota: <span>${p.quota_default} calls / key</span></span>
       </div>`
    : '';

  return `
    <div class="page-header">
      <h1>${escHtml(p.display_name)}</h1>
      <p>${escHtml(p.description || '')}</p>
    </div>
    ${infoStrip}

    <div class="plugin-tabs">
      <div class="plugin-tab active" onclick="switchPluginTab('${p.name}','test',this)">Live Test</div>
      <div class="plugin-tab" onclick="switchPluginTab('${p.name}','example',this)">Example Code</div>
    </div>

    <div class="plugin-panel active" id="ptab-${p.name}-test">
      <div class="card">
        <div class="card-title">Live Test</div>
        ${loggedIn ? '' : `<div class="text-muted" style="text-align:center;padding:18px 4px">🔒 登录后即可在线调试此接口（游客可查看下方「Example Code」示例）。<div style="margin-top:14px"><button class="btn btn-primary" onclick="goPage('auth')">登录 / 注册</button></div></div>`}
        <div class="test-panel"${loggedIn ? '' : ' style="display:none"'}>
          <div>
            <label class="form-label">API Key</label>
            <input class="form-input" id="tkey-${p.name}" placeholder="sk-…  (your API key)" style="font-family:var(--mono);font-size:12px" />
          </div>
          <div>
            <label class="form-label">Endpoint Path</label>
            <input class="form-input" id="turl-${p.name}" placeholder="/plugin-path/endpoint" value="${escHtml(testUrl)}" style="font-family:var(--mono);font-size:12px" />
          </div>
          <div>
            <label class="form-label">Method</label>
            <select class="form-input" id="tmethod-${p.name}" style="cursor:pointer">
              <option value="POST" ${testMethod==='POST'?'selected':''}>POST</option>
              <option value="GET"  ${testMethod==='GET' ?'selected':''}>GET</option>
              <option value="PUT"  ${testMethod==='PUT' ?'selected':''}>PUT</option>
            </select>
          </div>

          ${fileFieldsHtml}

          ${extraFieldsHtml
            ? `<div>
                 <label class="form-label">Parameters</label>
                 <div style="display:flex;flex-direction:column;gap:8px">${extraFieldsHtml}</div>
               </div>`
            : `<div>
                 <label class="form-label">Request Body (JSON)</label>
                 <textarea class="form-input" id="tbody-${p.name}" rows="5" style="font-family:var(--mono);font-size:12px;resize:vertical">${testBody}</textarea>
               </div>`
          }
          <div>
            <button class="btn btn-primary" onclick="runTest('${p.name}', ${!!extraFieldsHtml}, ${hasFiles})">▶ Send Request</button>
          </div>
          <div class="test-result-wrap" id="tresult-${p.name}" style="display:none">
            <div class="test-result-label">
              <span>Response</span>
              <span id="tstatus-${p.name}"></span>
            </div>
            <div class="test-result-body" id="tbody-out-${p.name}"></div>
            <div class="test-img-grid" id="timg-${p.name}"></div>
          </div>
        </div>
      </div>
    </div>

    <div class="plugin-panel" id="ptab-${p.name}-example">
      <div class="card">
        <div class="card-title">Sample Call</div>
        ${exampleHtml}
      </div>
    </div>`;
}

function buildExtraFields(pluginName, params) {
  return Object.entries(params).map(([k, v]) => {
    const id = `tparam-${pluginName}-${k}`;
    const isObj = v !== null && typeof v === 'object';
    const val = escHtml(isObj ? JSON.stringify(v, null, 2) : String(v ?? ''));

    // 如果是数组或对象，渲染出多行 textarea；如果只是单纯字符串，用单行 input
    const inputHtml = isObj
      ? `<textarea class="form-input" id="${id}" rows="4" style="font-family:var(--mono);font-size:12px;resize:vertical;width:100%" data-param="${escHtml(k)}">${val}</textarea>`
      : `<input class="form-input" id="${id}" value="${val}" style="font-family:var(--mono);font-size:12px;width:100%" data-param="${escHtml(k)}" />`;

    return `<div style="display:flex;align-items:flex-start;gap:8px">
      <span style="font-family:var(--mono);font-size:11px;color:var(--text3);width:120px;flex-shrink:0;padding-top:10px">${escHtml(k)}</span>
      <div style="flex:1">${inputHtml}</div>
    </div>`;
  }).join('');
}

function switchPluginTab(pluginName, tab, el) {
  ['example','test'].forEach(t => {
    document.getElementById(`ptab-${pluginName}-${t}`).classList.toggle('active', t===tab);
  });
  el.closest('.plugin-tabs').querySelectorAll('.plugin-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function copyCode(id) {
  navigator.clipboard.writeText(document.getElementById(id).textContent).then(() => toast('Copied!'));
}

function parseExample(code) {
  const result = { method:'POST', url:'', body:{} };
  const mM = code.match(/\.(get|post|put|patch|delete)\s*\(/i);
  if (mM) result.method = mM[1].toUpperCase();
  const uM = code.match(/["']([^"']*\/v1[^"'\s]*)["']/);
  if (uM) { try { result.url = new URL(uM[1]).pathname; } catch(_) { result.url = uM[1]; } }
  const jM = code.match(/json\s*=\s*\{([^}]+)\}/s) || code.match(/data\s*=\s*\{([^}]+)\}/s);
  if (jM) {
    try {
      const jsonStr = jM[1].replace(/'/g, '"').replace(/True/g,'true').replace(/False/g,'false').replace(/None/g,'null');
      result.body = JSON.parse('{' + jsonStr + '}');
    } catch(_) { result.body = {}; }
  }
  return result;
}

async function runTest(pluginName, hasExtraFields, hasFiles) {
  const apiKey  = document.getElementById(`tkey-${pluginName}`).value.trim();
  const urlPath = document.getElementById(`turl-${pluginName}`).value.trim();
  const method  = document.getElementById(`tmethod-${pluginName}`).value;

  if (!apiKey) { toast('Enter an API key first', 'error'); return; }
  if (!urlPath) { toast('Enter an endpoint path', 'error'); return; }

  // 1. Check and aggregate files if they exist
  let fd = null;
  let isMultipart = false;

  if (hasFiles) {
    const fileInputs = document.querySelectorAll(`[id^="tfile-${pluginName}-"]`);
    let filesSelected = false;
    fileInputs.forEach(inp => { if (inp.files && inp.files.length > 0) filesSelected = true; });

    if (filesSelected) {
      isMultipart = true;
      fd = new FormData();
      fileInputs.forEach(inp => {
        const fKey = inp.dataset.filekey;
        for (let i = 0; i < inp.files.length; i++) {
          fd.append(fKey, inp.files[i]);
        }
      });
    }
  }

  // 2. Build Text Params
  let params = {};
  let bodyRaw = '';
  if (hasExtraFields) {
    document.querySelectorAll(`[id^="tparam-${pluginName}-"]`).forEach(inp => {
      let v = inp.value;
      try {
        // 尝试解析 JSON（把由于编辑或预填进入的如 "[{...}]" 变回真实数组）
        v = JSON.parse(v);
      } catch(e) {
        // 如果是普通的纯字符串解析失败，忽略即可，保持原本的字符串格式
      }
      params[inp.dataset.param] = v;
    });
    bodyRaw = JSON.stringify(params);
  } else {
    bodyRaw = (document.getElementById(`tbody-${pluginName}`) || {}).value || '{}';
    try { params = JSON.parse(bodyRaw); } catch(_) {}
  }

  const resultWrap = document.getElementById(`tresult-${pluginName}`);
  const statusEl   = document.getElementById(`tstatus-${pluginName}`);
  const bodyOutEl  = document.getElementById(`tbody-out-${pluginName}`);
  const imgGrid    = document.getElementById(`timg-${pluginName}`);

  resultWrap.style.display = '';
  bodyOutEl.innerHTML = `<span class="test-spinner"></span> Sending…`;
  statusEl.innerHTML  = '';
  imgGrid.innerHTML   = '';

  try {
    const opts = { method, headers: { 'Authorization': `Bearer ${apiKey}` } };

    if (method !== 'GET') {
      if (isMultipart) {
        // Multipart FormData behavior
        if (hasExtraFields) {
          for (const [k, v] of Object.entries(params)) {
            // FormData 传值不能传 object，如果是 object 必须转回 string (例如列表对象)
            fd.append(k, typeof v === 'object' ? JSON.stringify(v) : v);
          }
        } else {
          let pObj = {};
          try { pObj = JSON.parse(bodyRaw); } catch(_) {}
          if (Object.keys(pObj).length > 0) {
            for (const [k, v] of Object.entries(pObj)) {
              fd.append(k, typeof v === 'object' ? JSON.stringify(v) : v);
            }
          } else {
            fd.append('data', bodyRaw);
          }
        }
        opts.body = fd;
        // Don't set Content-Type header when using FormData; fetch handles the boundary
      } else {
        // Default application/json behavior
        opts.headers['Content-Type'] = 'application/json';
        if (hasExtraFields) {
          opts.body = JSON.stringify(params);
        } else {
          try { opts.body = JSON.stringify(JSON.parse(bodyRaw)); }
          catch(_) { opts.body = bodyRaw; }
        }
      }
    }

    const resp = await fetch(urlPath, opts);
    const ok   = resp.ok;
    statusEl.innerHTML = `<span class="tag ${ok?'tag-green':'tag-red'}">${resp.status} ${resp.statusText}</span>`;

    let data;
    const ct = resp.headers.get('content-type') || '';
    if (ct.includes('application/json')) { data = await resp.json(); }
    else { data = await resp.text(); }

    if (data && typeof data === 'object' && Array.isArray(data.images)) {
      bodyOutEl.textContent = JSON.stringify({...data, images: [`[${data.images.length} image(s) — preview below]`]}, null, 2);
      imgGrid.innerHTML = data.images.map(b64 => `<img src="data:image/png;base64,${b64}" alt="result" />`).join('');
    } else if (data && typeof data === 'object' && Array.isArray(data.data) && data.data[0]?.url) {
      bodyOutEl.textContent = JSON.stringify(data, null, 2);
      imgGrid.innerHTML = data.data.filter(d=>d.url).map(d => `<img src="${d.url}" alt="result" />`).join('');
    } else {
      bodyOutEl.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
    }
  } catch(e) {
    statusEl.innerHTML = `<span class="tag tag-red">Error</span>`;
    bodyOutEl.textContent = e.message;
  }
}
