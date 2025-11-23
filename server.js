// server.js
const express = require("express");
const bodyParser = require("body-parser");
const cors = require("cors");

const app = express();
app.use(cors());
app.use(bodyParser.json({ limit: "1mb" }));

const PORT = process.env.PORT || 8080;
const BROADCAST_AUTH = process.env.BROADCAST_AUTH || ""; // optional token to secure /send
const KEEPALIVE_INTERVAL_MS = 15000;

let clients = new Set();

function sendToClient(res, payload) {
  try {
    res.write(`data: ${JSON.stringify(payload)}\n\n`);
  } catch (err) {
    // ignore: client likely disconnected
  }
}

// Root
app.get("/", (req, res) => {
  res.type("text/plain").send("SSE Broadcaster Running");
});

// SSE endpoint
app.get("/stream", (req, res) => {
  // Required SSE headers
  res.set({
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
    "Access-Control-Allow-Origin": "*",
  });

  // Send initial comment to establish stream
  res.write(`: connected\n\n`);
  res.flushHeaders && res.flushHeaders();

  // Add to clients
  clients.add(res);
  console.log("[SSE] Client connected — total:", clients.size);

  // Keep-alive ping (comment line) to prevent proxies from closing idle connections
  const keepAlive = setInterval(() => {
    try {
      // sending a comment is safest: begins with colon
      res.write(`: ping\n\n`);
    } catch (err) {
      // ignore
    }
  }, KEEPALIVE_INTERVAL_MS);

  // Remove client on close
  req.on("close", () => {
    clearInterval(keepAlive);
    clients.delete(res);
    try { res.end(); } catch (e) {}
    console.log("[SSE] Client disconnected — total:", clients.size);
  });
});

// POST /send — broadcast JSON payload to all connected SSE clients
app.post("/send", (req, res) => {
  // Optional auth
  if (BROADCAST_AUTH) {
    const authHeader = req.headers["authorization"] || "";
    if (!authHeader.startsWith("Bearer ") || authHeader.slice(7) !== BROADCAST_AUTH) {
      return res.status(401).json({ error: "unauthorized" });
    }
  }

  const payload = req.body;
  if (!payload) return res.status(400).json({ error: "missing json body" });

  // Broadcast non-blocking: iterate clients and write
  for (const client of clients) {
    sendToClient(client, payload);
  }

  console.log("[SEND] Broadcast to", clients.size, "clients:", payload);
  return res.json({ ok: true, clients: clients.size });
});

// OPTIONS preflight for /send (CORS)
app.options("/send", (req, res) => {
  res.set({
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
  });
  res.sendStatus(204);
});

app.listen(PORT, () => {
  console.log(`SSE broadcaster listening on port ${PORT}`);
});
