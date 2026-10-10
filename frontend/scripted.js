
/* ==========================================================
   Batchwise frontend
   1. State
   2. Helpers
   3. API
   4. Calculations
   5. Rendering
   6. Event wiring
   7. Seller assistant
   8. Startup
   ========================================================== */

/* ---------- 1. State ---------- */
let weekLabel = "";
let products = [];
let selectedIndex = 0;
let plans = {};
let captions = {};


/* ---------- 2. Helpers ---------- */
const $ = (id) => document.getElementById(id);

/** Format a number as RM 1,234.50 */
const formatRM = (n) =>
  "RM " + Number(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** Median of a list of numbers */
const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;

  return sorted.length % 2
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
};

/** Escape text before putting it into innerHTML */
const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  }[c]));


/* ---------- 3. API ---------- */
async function api(path, options = {}) {
  let response;

  try {
    response = await fetch(path, options);
  } catch (e) {
    throw new Error(
      "Cannot reach the Batchwise backend. Check that FastAPI is running and the frontend uses the correct server address."
    );
  }

  let body;

  try {
    body = await response.json();
  } catch (e) {
    throw new Error(
      "The backend returned an invalid response. Check the API endpoint."
    );
  }

  if (!response.ok) {
    throw new Error(
      body.detail || `Request failed (${response.status}).`
    );
  }

  return body;
}


/* ---------- 4. Calculations ---------- */

/**
 * Suggest a batch size from historical sales.
 * Requires at least 3 completed weeks.
 */
function calcSuggestion(p) {
  const units = p.sales.map((s) => s.u);

  if (units.length < 3) return null;

  const applyLimit = (x) =>
    p.limit ? Math.min(x, p.limit) : x;

  const mid = Math.round(median(units));

  return {
    sug: applyLimit(mid),
    lo: applyLimit(Math.min(...units)),
    hi: applyLimit(Math.max(...units)),
    raw: mid,
    capped: Boolean(p.limit && mid > p.limit),
  };
}

/** Generate a promotion caption draft locally */
function buildCaption(p) {
  return (
    `Fresh batch alert! ${p.name} (RM ${p.price.toFixed(2)}) is back the week of ${p.week}. ` +
    `I'm preparing ${plans[p.id]} ${p.unit} for the week, so come early to grab yours!`
  );
}


/* ---------- 5. Rendering ---------- */

/** Overview: one tile per beverage */
function renderOverview() {
  const tiles = products
    .map((q, i) => {
      const suggestion = calcSuggestion(q);
      const plan = plans[q.id];

      return (
        `<button type="button" class="stat${i === selectedIndex ? " on" : ""}" data-i="${i}">` +
        `<span class="tag">${esc(q.name)}</span>` +
        `<b>${plan != null ? plan + " " + esc(q.unit) : "Not planned"}</b>` +
        `<span class="mut">${suggestion ? "Suggested " + suggestion.sug : "No suggestion yet"}</span>` +
        `</button>`
      );
    })
    .join("");

  return `
    <section class="card">
      <h2>Next week at a glance <span class="mut">· ${esc(weekLabel)}</span></h2>
      <div class="grid">${tiles}</div>
    </section>`;
}


/** Main card: suggested quantity and seller's plan */
function renderDecision(p, suggestion, plan) {
  let html = `
    <section class="card hero">
      <div class="tag">Your next batch decision</div>
      <h2>${esc(p.name)} — ${esc(p.week)}</h2>`;

  if (suggestion) {
    html += `
      <div class="row" style="gap:20px;align-items:flex-end">
        <div>
          <div class="mut">Suggested to prepare for the week</div>
          <div class="big">${suggestion.sug}</div>
          <div class="mut">
            ${esc(p.unit)} · about ${Math.round(suggestion.sug / p.days)}
            per selling day (${p.days} days)
          </div>
        </div>

        <div>
          <div class="mut">Planning range</div>
          <b style="font-size:1.4rem">${suggestion.lo}–${suggestion.hi}</b>
          <span class="mut">${esc(p.unit)}</span><br>
          <span class="pill">Limited evidence · ${p.sales.length} weeks</span>
        </div>
      </div>

      <div class="box">
        <b>Why this number:</b>
        ${p.sales.length} comparable past weeks sold
        ${p.sales.map((s) => s.u).join(", ")} ${esc(p.unit)}.
        The middle (median) value is ${suggestion.raw}.
        The range is the lowest and highest of those weeks.<br>
        <span class="mut">
          Based on completed sales recorded in MongoDB.
          This is a planning reference, not a validated prediction.
        </span>
      </div>`;
  } else {
    html += `
      <div class="warnbox">
        Not enough completed sales history to recommend a quantity.
      </div>
      <p class="mut">
        Only ${p.sales.length} completed week${p.sales.length === 1 ? "" : "s"}
        on file; at least 3 are needed. You can still enter your own batch.
      </p>`;
  }

  const defaultQty =
    plan ?? (suggestion ? suggestion.sug : "");

  const planStatus =
    plan != null
      ? `<span class="stat" style="display:inline-block">
           <span class="tag">Seller's choice</span>
           <b>${plan} ${esc(p.unit)}</b>
         </span>` +
        (suggestion
          ? ` <span class="mut">vs suggested ${suggestion.sug}</span>`
          : "")
      : `<span class="mut">No plan confirmed yet.</span>`;

  html += `
      <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">

      <div class="row">
        <label for="qty">
          <b>Your planned batch for ${esc(p.name)}</b>
        </label>

        <input
          id="qty"
          type="number"
          min="0"
          step="1"
          ${p.limit ? `max="${p.limit}"` : ""}
          style="width:100px"
          value="${defaultQty}"
        >

        <button class="p" id="ok">Confirm my plan</button>
      </div>

      <div id="planmsg" style="margin-top:8px">${planStatus}</div>
    </section>`;

  return html;
}


/** Evidence card: product facts and sales history */
function renderEvidence(p) {
  const totalUnits = p.sales.reduce((a, s) => a + s.u, 0);
  const gross = p.sales.reduce((a, s) => a + s.revenue, 0);
  const weeks = p.sales.length;

  return `
    <div class="sec">Evidence</div>

    <section class="card">
      <div class="grid">
        <div class="stat">
          <span class="tag">Price</span>
          <b>${formatRM(p.price)}</b>
        </div>

        <div class="stat">
          <span class="tag">Category</span>
          <b>${esc(p.category)}</b>
        </div>

        <div class="stat">
          <span class="tag">Milk-based</span>
          <b>${p.milk_based ? "Yes" : "No"}</b>
        </div>

        <div class="stat">
          <span class="tag">Temperatures</span>
          <b>${p.temperatures.map(esc).join(", ") || "Not listed"}</b>
        </div>

        <div class="stat">
          <span class="tag">Sizes</span>
          <b>${p.sizes.map(esc).join(", ") || "Not listed"}</b>
        </div>

        <div class="stat" style="background:var(--accbg)">
          <span class="tag">Units sold in these weeks</span>
          <b>${totalUnits} ${esc(p.unit)}</b>
          ${formatRM(gross)} over ${weeks} week${weeks === 1 ? "" : "s"}
        </div>
      </div>

      <details>
        <summary>Inspect weeks behind these sales</summary>
        <div class="scroll">
          <table>
            <tr>
              <th>Week</th>
              <th>Units sold</th>
              <th>Gross sales</th>
            </tr>

            ${p.sales.map((s) => `
              <tr>
                <td>${esc(s.d)}</td>
                <td>${s.u}</td>
                <td>${formatRM(s.revenue)}</td>
              </tr>
            `).join("")}
          </table>
        </div>
      </details>

      <details>
        <summary>How was this calculated?</summary>
        <p class="mut">
          Suggested weekly quantity = median units sold across the three
          latest completed weeks in MongoDB. Range = lowest and highest
          of those weeks. With fewer than three weeks of history no
          suggestion is shown.
        </p>
      </details>
    </section>`;
}


/** Feedback card: recent customer comments */
function renderFeedback(p) {
  const body = p.comments.length
    ? p.comments
        .map(([comment]) =>
          `<blockquote>“${esc(comment)}”</blockquote>`
        )
        .join("")
    : `<p class="mut">No comments are recorded for this beverage.</p>`;

  return `
    <div class="sec">Feedback</div>

    <section class="card">
      <h2>
        Recent customer feedback
        <span class="mut">(up to 20 comments)</span>
      </h2>
      ${body}
    </section>`;
}


/** Promotion card: editable caption */
function renderPromotion(p, plan) {
  let html = `
    <div class="sec">Promotion draft</div>

    <section class="card">
      <h2>
        Caption
        <span class="mut">(generated locally; not posted)</span>
      </h2>`;

  if (plan == null) {
    html += `
      <p class="mut">
        Confirm your planned batch above and a caption will appear here.
      </p>`;
  } else {
    if (captions[p.id] == null) {
      captions[p.id] = buildCaption(p);
    }

    html += `
      <textarea id="cap" aria-label="Promotion caption">${esc(captions[p.id])}</textarea>

      <div class="row" style="margin-top:8px">
        <button id="cp" class="p">Copy caption</button>
        <button id="rg">Regenerate</button>
        <span class="mut" id="cpm">
          Not posted anywhere. Edit freely, then copy.
        </span>
      </div>`;
  }

  return html + `</section>`;
}


/** Render the selected product */
function render() {
  const p = products[selectedIndex];

  if (!p) return;

  const suggestion = calcSuggestion(p);
  const plan = plans[p.id];

  $("app").innerHTML =
    renderOverview() +
    renderDecision(p, suggestion, plan) +
    renderEvidence(p) +
    renderFeedback(p) +
    renderPromotion(p, plan);

  bindPageEvents(p);
}


/* ---------- 6. Event wiring ---------- */

/** Product dropdown */
$("sel").onchange = (e) => {
  selectedIndex = Number(e.target.value);
  render();
};


/** Reset all saved plans */
$("reset").onclick = async () => {
  try {
    await api("/api/plans", { method: "DELETE" });

    plans = {};
    captions = {};
    selectedIndex = 0;

    $("sel").value = "0";
    render();
  } catch (e) {
    alert(e.message);
  }
};


/** Handlers for dynamically rendered elements */
function bindPageEvents(p) {
  // Overview tiles switch product
  document.querySelectorAll("[data-i]").forEach((b) => {
    b.onclick = () => {
      selectedIndex = Number(b.dataset.i);
      $("sel").value = String(selectedIndex);
      render();
    };
  });

  // Confirm planned batch
  $("ok").onclick = async () => {
    const input = $("qty");
    const rawValue = input.valueAsNumber;

    if (
      input.value.trim() === "" ||
      !Number.isFinite(rawValue) ||
      rawValue < 0 ||
      !Number.isInteger(rawValue)
    ) {
      $("planmsg").textContent =
        "Enter a valid non-negative whole number.";
      return;
    }

    if (p.limit && rawValue > p.limit) {
      $("planmsg").textContent =
        `The maximum allowed quantity is ${p.limit}.`;
      return;
    }

    try {
      plans = await api(
        "/api/plans/" + encodeURIComponent(p.id),
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            quantity: rawValue,
          }),
        }
      );

      // Rebuild the caption for the newly confirmed quantity
      captions[p.id] = null;

      render();
    } catch (e) {
      $("planmsg").textContent = e.message;
    }
  };

  // Caption editor
  if ($("cap")) {
    $("cap").oninput = (e) => {
      captions[p.id] = e.target.value;
    };

    $("rg").onclick = () => {
      captions[p.id] = buildCaption(p);
      render();
    };

    $("cp").onclick = async () => {
      const caption = $("cap").value;

      try {
        await navigator.clipboard.writeText(caption);
        $("cpm").textContent = "Copied!";
      } catch (e) {
        $("cap").select();
        $("cpm").textContent =
          "Press Ctrl/Cmd+C to copy.";
      }
    };
  }
}


/* ---------- 7. Seller assistant ---------- */
function setupAssistant() {
  const log = $("chatlog");
  const input = $("chatin");
  const sendBtn = $("chatsend");
  const note = $("chatnote");
  const fab = $("chatfab");
  const panel = $("chat");

  const suggestedQuestions = [
    "Why this quantity?",
    "What do customers say about this drink?",
    "What should I check before planning?",
    "Help me improve my caption",
  ];

  $("chips").innerHTML = suggestedQuestions
    .map((q) => `<button type="button">${esc(q)}</button>`)
    .join("");

  note.textContent = "Uses Gemini when configured.";

  // Open and close the chat panel
  const openChat = () => {
    panel.hidden = false;
    fab.hidden = true;
    fab.setAttribute("aria-expanded", "true");
    input.focus();
  };

  const closeChat = () => {
    panel.hidden = true;
    fab.hidden = false;
    fab.setAttribute("aria-expanded", "false");
    fab.focus();
  };

  fab.onclick = openChat;
  $("chatclose").onclick = closeChat;

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden) {
      closeChat();
    }
  });

  // Conversation state
  const history = [];
  let busy = false;

  function addMessage(cls, text) {
    const div = document.createElement("div");

    div.className = "msg " + cls;
    div.textContent = text;

    log.appendChild(div);
    log.scrollTop = log.scrollHeight;

    return div;
  }

  async function ask(text) {
    text = text.trim();

    if (!text || busy) return;

    busy = true;
    sendBtn.disabled = true;

    input.value = "";

    addMessage("u", text);
    history.push({
      role: "user",
      content: text,
    });

    const reply = addMessage("a", "Thinking…");

    try {
      const result = await api("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          product_id: products[selectedIndex].id,
          message: text,
          history: history.slice(0, -1).slice(-10),
        }),
      });

      reply.textContent = result.reply;

      history.push({
        role: "assistant",
        content: result.reply,
      });
    } catch (e) {
      history.pop();
      reply.textContent = e.message;
    }

    busy = false;
    sendBtn.disabled = false;
    input.focus();
  }

  sendBtn.onclick = () => ask(input.value);

  input.onkeydown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      ask(input.value);
    }
  };

  $("chips").onclick = (e) => {
    if (e.target.tagName === "BUTTON") {
      ask(e.target.textContent);
    }
  };

  // Clear the conversation when plans are reset
  $("reset").addEventListener("click", () => {
    history.length = 0;
    log.innerHTML = "";
  });
}


/* ---------- 8. Startup ---------- */

/** Disable assistant controls if data cannot load */
function disableAssistant(message) {
  $("chatnote").textContent = message;
  $("chatin").disabled = true;
  $("chatsend").disabled = true;
  $("chatfab").disabled = true;
}


/** Load initial data from FastAPI */
async function start() {
  try {
    const data = await api("/api/products");
    const savedPlans = await api("/api/plans");

    weekLabel = data.week;
    products = data.products;
    plans = savedPlans;

    if (!products.length) {
      $("app").innerHTML = `
        <section class="card warnbox">
          No beverages were found in the configured MongoDB database.
        </section>`;

      $("sel").disabled = true;

      disableAssistant(
        "Add beverage records to the beverages collection to use the assistant."
      );

      return;
    }

    $("sel").innerHTML = products
      .map((p, i) =>
        `<option value="${i}">${esc(p.name)} — ${esc(p.week)}</option>`
      )
      .join("");

    render();
  } catch (e) {
    $("app").innerHTML = `
      <section class="card warnbox">${esc(e.message)}</section>`;

    $("reset").disabled = true;
    $("sel").disabled = true;

    disableAssistant(e.message);

    return;
  }

  setupAssistant();
}

start();
