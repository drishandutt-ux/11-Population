"use client";

import { useState, useRef } from "react";
import { api, Session } from "@/lib/api";
import {
  Type, Upload, Youtube, CheckCircle, Loader2, X, Plus,
  FileText, FileSpreadsheet, FileImage, FileCode, Presentation, Sparkles,
} from "lucide-react";

type IngestTab = "text" | "document" | "youtube" | "llm-search";
type LLMModel = "claude" | "gemini" | "openai";

interface Props {
  session: Session;
  onIngested: () => void;
  onGoToAgents: () => void;
}

// ── File type catalogue ──────────────────────────────────────────────────────
const FILE_TYPES = [
  {
    label: "Documents",
    icon: <FileText className="w-3.5 h-3.5" />,
    exts: ".pdf, .docx, .txt, .md, .rtf",
    color: "text-blue-400",
  },
  {
    label: "Spreadsheets",
    icon: <FileSpreadsheet className="w-3.5 h-3.5" />,
    exts: ".xlsx, .xls, .csv, .tsv, .ods",
    color: "text-emerald-400",
  },
  {
    label: "Presentations",
    icon: <Presentation className="w-3.5 h-3.5" />,
    exts: ".pptx",
    color: "text-orange-400",
  },
  {
    label: "Images & Graphics",
    icon: <FileImage className="w-3.5 h-3.5" />,
    exts: ".jpg, .png, .gif, .webp, .bmp, .tiff",
    color: "text-purple-400",
    note: "Vision AI",
  },
  {
    label: "Data / Markup",
    icon: <FileCode className="w-3.5 h-3.5" />,
    exts: ".json, .xml, .html, .svg",
    color: "text-teal-400",
  },
];

const ACCEPT =
  ".pdf,.docx,.txt,.md,.rst,.rtf,.log," +
  ".xlsx,.xls,.csv,.tsv,.ods," +
  ".pptx," +
  ".jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff,.tif," +
  ".json,.xml,.html,.htm,.svg";

function fileIcon(filename: string) {
  const lower = filename.toLowerCase();
  if (/\.(xlsx?|csv|tsv|ods)$/.test(lower)) return <FileSpreadsheet className="w-5 h-5 text-emerald-400 shrink-0" />;
  if (/\.(pptx?)$/.test(lower))             return <Presentation   className="w-5 h-5 text-orange-400 shrink-0" />;
  if (/\.(jpe?g|png|gif|webp|bmp|tiff?)$/.test(lower)) return <FileImage className="w-5 h-5 text-purple-400 shrink-0" />;
  if (/\.(json|xml|html?|svg)$/.test(lower)) return <FileCode      className="w-5 h-5 text-teal-400 shrink-0" />;
  return <FileText className="w-5 h-5 text-primary shrink-0" />;
}

function isImageFile(filename: string) {
  return /\.(jpe?g|png|gif|webp|bmp|tiff?)$/i.test(filename);
}

export default function InputPanel({ session, onIngested, onGoToAgents }: Props) {
  const [tab, setTab]                       = useState<IngestTab>("text");
  const [text, setText]                     = useState("");
  const [ytUrl, setYtUrl]                   = useState("");
  const [selectedFiles, setSelectedFiles]   = useState<File[]>([]);
  const [imagePreviews, setImagePreviews]   = useState<Record<string, string>>({});
  const [isDragging, setIsDragging]         = useState(false);
  const [loading, setLoading]               = useState(false);
  const [ingestProgress, setIngestProgress] = useState<string | null>(null);
  const [success, setSuccess]               = useState<string | null>(null);
  const [error, setError]                   = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // LLM Search state
  const [llmQuery, setLlmQuery]           = useState(session.query);
  const [llmModel, setLlmModel]           = useState<LLMModel>("claude");
  const [llmContextFile, setLlmContextFile] = useState<File | null>(null);
  const llmFileRef = useRef<HTMLInputElement>(null);

  // ── File management ─────────────────────────────────────────────────────────

  function addFiles(incoming: File[]) {
    setError(null);
    setSelectedFiles((prev) => {
      const existingNames = new Set(prev.map((f) => f.name));
      const novel = incoming.filter((f) => !existingNames.has(f.name));
      return [...prev, ...novel];
    });
    for (const file of incoming) {
      if (isImageFile(file.name)) {
        const reader = new FileReader();
        reader.onload = (e) =>
          setImagePreviews((prev) => ({ ...prev, [file.name]: e.target?.result as string }));
        reader.readAsDataURL(file);
      }
    }
  }

  function removeFile(name: string) {
    setSelectedFiles((prev) => prev.filter((f) => f.name !== name));
    setImagePreviews((prev) => { const next = { ...prev }; delete next[name]; return next; });
    if (fileRef.current) fileRef.current.value = "";
  }

  function clearFiles() {
    setSelectedFiles([]);
    setImagePreviews({});
    if (fileRef.current) fileRef.current.value = "";
  }

  // ── Drag-and-drop ───────────────────────────────────────────────────────────

  function onDragOver(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(true);
  }
  function onDragLeave() { setIsDragging(false); }
  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) addFiles(files);
  }

  // ── Submit ──────────────────────────────────────────────────────────────────

  async function submit() {
    setLoading(true);
    setError(null);
    setSuccess(null);
    setIngestProgress(null);
    try {
      if (tab === "text") {
        if (!text.trim()) throw new Error("Enter some text first");
        await api.ingest.text(session.id, text);
        setSuccess("Text ingested — building knowledge graph…");
      } else if (tab === "youtube") {
        if (!ytUrl.trim()) throw new Error("Enter a YouTube URL");
        await api.ingest.youtube(session.id, ytUrl);
        setSuccess("YouTube video queued — extracting transcript, visuals, comments & metadata…");
      } else if (tab === "llm-search") {
        if (!llmQuery.trim()) throw new Error("Enter a research query");
        setIngestProgress("Categorising query & generating research paper…");
        await api.ingest.llmSearch(session.id, { query: llmQuery, llm: llmModel, contextFile: llmContextFile });
        setSuccess("Research paper queued — AI is generating it now (30–60 seconds)…");
      } else {
        if (selectedFiles.length === 0) throw new Error("Select at least one file");
        let done = 0;
        for (const file of selectedFiles) {
          setIngestProgress(
            selectedFiles.length > 1
              ? `Ingesting "${file.name}" (${done + 1} of ${selectedFiles.length})…`
              : `Ingesting "${file.name}"…`
          );
          await api.ingest.document(session.id, file);
          done++;
        }
        const imgCount = selectedFiles.filter((f) => isImageFile(f.name)).length;
        if (selectedFiles.length === 1) {
          setSuccess(
            isImageFile(selectedFiles[0].name)
              ? `"${selectedFiles[0].name}" analysed via Vision AI — ingesting…`
              : `"${selectedFiles[0].name}" ingested — building knowledge graph…`
          );
        } else {
          setSuccess(
            `${selectedFiles.length} files ingested` +
            (imgCount > 0 ? ` (${imgCount} via Vision AI)` : "") +
            " — building knowledge graph…"
          );
        }
      }
      onIngested();
      setTimeout(() => onGoToAgents(), 1400);
    } catch (e: any) {
      setError(e.message || "Failed to ingest");
    } finally {
      setLoading(false);
      setIngestProgress(null);
    }
  }

  const tabs: { key: IngestTab; label: string; icon: React.ReactNode }[] = [
    { key: "text",       label: "Text",       icon: <Type     className="w-3.5 h-3.5" /> },
    { key: "document",   label: "File",       icon: <Upload   className="w-3.5 h-3.5" /> },
    { key: "youtube",    label: "YouTube",    icon: <Youtube  className="w-3.5 h-3.5" /> },
    { key: "llm-search", label: "LLM Search", icon: <Sparkles className="w-3.5 h-3.5" /> },
  ];

  const canSubmit =
    !loading &&
    (tab === "text"       ? text.trim().length > 0
    : tab === "youtube"   ? ytUrl.trim().length > 0
    : tab === "llm-search" ? llmQuery.trim().length > 0
    :                        selectedFiles.length > 0);

  const hasImages = selectedFiles.some((f) => isImageFile(f.name));

  return (
    <div className="h-full overflow-auto p-6">
      <div className="max-w-2xl mx-auto space-y-5">

        {/* Query recap */}
        <div className="border border-border/60 rounded-lg p-4">
          <div className="text-[10px] text-muted-foreground uppercase tracking-widest mb-1.5">
            Analysis query
          </div>
          <p className="text-sm text-foreground font-medium">{session.query}</p>
          <p className="text-xs text-muted-foreground/60 mt-1.5">
            Ingest one or more sources — all are merged into the same knowledge graph before agents are spawned.
          </p>
        </div>

        {/* Input tabs */}
        <div className="border border-border/60 rounded-lg overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-border/60">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => { setTab(t.key); setError(null); setSuccess(null); }}
                className={`flex items-center gap-1.5 px-5 py-3 text-xs font-medium transition-colors flex-1 justify-center ${
                  tab === t.key
                    ? "text-primary bg-primary/8 border-b border-primary"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.icon}
                {t.label}
              </button>
            ))}
          </div>

          <div className="p-5 space-y-4">
            {/* ── Text ── */}
            {tab === "text" && (
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Paste articles, research papers, transcripts, notes, or any context relevant to your query…"
                rows={10}
                className="w-full bg-muted/40 border border-border/60 rounded-md px-3.5 py-3 text-sm text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50 resize-none"
              />
            )}

            {/* ── YouTube ── */}
            {tab === "youtube" && (
              <div className="space-y-4">
                <input
                  value={ytUrl}
                  onChange={(e) => setYtUrl(e.target.value)}
                  placeholder="https://www.youtube.com/watch?v=…"
                  className="w-full bg-muted/40 border border-border/60 rounded-md px-3.5 py-2.5 text-sm text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
                />

                {/* What gets extracted */}
                <div className="rounded-lg border border-border/50 bg-muted/20 px-4 py-3 space-y-2">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-medium">
                    What gets extracted
                  </p>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs text-muted-foreground/80">
                    {[
                      ["📋", "Full metadata", "title, channel, views, likes, tags"],
                      ["🎙️", "Timestamped transcript", "captions or Whisper AI fallback"],
                      ["🪝", "Hook / opening", "first 90 seconds highlighted"],
                      ["🖼️", "Thumbnail analysis", "Claude Vision describes visual content"],
                      ["🎬", "Key visual frames", "5 frames across the video + Vision AI"],
                      ["📖", "Chapters & description", "full structure of the video"],
                      ["💬", "Top comments", "20 most-liked viewer reactions"],
                    ].map(([icon, label, detail]) => (
                      <div key={label} className="flex items-start gap-1.5">
                        <span className="text-sm leading-none mt-0.5 shrink-0">{icon}</span>
                        <div>
                          <span className="font-medium text-foreground/80">{label}</span>
                          <span className="text-muted-foreground/55"> — {detail}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <p className="text-[10px] text-muted-foreground/50">
                  Deep extraction takes 1–3 minutes depending on video length. Progress shown in the status indicator.
                </p>
              </div>
            )}

            {/* ── File upload ── */}
            {tab === "document" && (
              <div className="space-y-4">

                {/* Selected files list */}
                {selectedFiles.length > 0 ? (
                  <div className="space-y-2">
                    {selectedFiles.map((file) => (
                      <div
                        key={file.name}
                        className="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-border/50 bg-muted/20"
                      >
                        {/* Thumbnail or icon */}
                        {imagePreviews[file.name] ? (
                          <img
                            src={imagePreviews[file.name]}
                            alt=""
                            className="w-9 h-9 object-cover rounded border border-border/40 shrink-0"
                          />
                        ) : (
                          <span className="shrink-0">{fileIcon(file.name)}</span>
                        )}

                        {/* Name + size */}
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-medium text-foreground truncate">{file.name}</p>
                          <p className="text-[10px] text-muted-foreground/55">
                            {(file.size / 1024).toFixed(1)} KB
                            {isImageFile(file.name) && " · Vision AI"}
                          </p>
                        </div>

                        {/* Remove */}
                        <button
                          onClick={() => removeFile(file.name)}
                          className="text-muted-foreground/40 hover:text-foreground transition-colors shrink-0"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ))}

                    {/* Add more */}
                    <button
                      onClick={() => fileRef.current?.click()}
                      className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg border border-dashed border-border/50 text-xs text-muted-foreground/60 hover:text-foreground hover:border-primary/40 transition-all"
                    >
                      <Plus className="w-3 h-3" />
                      Add more files
                    </button>
                  </div>
                ) : (
                  /* Drop zone (empty state) */
                  <div
                    onClick={() => fileRef.current?.click()}
                    onDragOver={onDragOver}
                    onDragLeave={onDragLeave}
                    onDrop={onDrop}
                    className={`border border-dashed rounded-lg p-8 text-center cursor-pointer transition-all ${
                      isDragging
                        ? "border-primary/70 bg-primary/8"
                        : "border-border/60 hover:border-primary/40 hover:bg-muted/30"
                    }`}
                  >
                    <Upload className="w-7 h-7 text-muted-foreground/40 mx-auto mb-2" />
                    <p className="text-sm text-foreground/80 font-medium mb-0.5">
                      Click or drag files here
                    </p>
                    <p className="text-xs text-muted-foreground/50">
                      Multiple files supported — any format below, no executables
                    </p>
                  </div>
                )}

                {/* Hidden file input — always multiple */}
                <input
                  ref={fileRef}
                  type="file"
                  accept={ACCEPT}
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    const files = Array.from(e.target.files ?? []);
                    if (files.length > 0) addFiles(files);
                    // Reset input so the same file can be re-added after removal
                    e.target.value = "";
                  }}
                />

                {/* Supported formats grid (only when nothing selected) */}
                {selectedFiles.length === 0 && (
                  <div className="grid grid-cols-2 gap-2">
                    {FILE_TYPES.map((ft) => (
                      <div
                        key={ft.label}
                        className="flex items-start gap-2.5 rounded-md border border-border/40 px-3 py-2.5 bg-muted/15"
                      >
                        <span className={`mt-0.5 ${ft.color}`}>{ft.icon}</span>
                        <div>
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs font-medium text-foreground/80">{ft.label}</span>
                            {ft.note && (
                              <span className="text-[10px] text-primary/70 border border-primary/30 rounded px-1">
                                {ft.note}
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-muted-foreground/50">{ft.exts}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* ── LLM Search ── */}
            {tab === "llm-search" && (
              <div className="space-y-4">

                {/* Model selector */}
                <div>
                  <p className="text-[10px] text-muted-foreground/60 uppercase tracking-widest mb-2">Select AI Model</p>
                  <div className="flex gap-2">
                    {(
                      [
                        { id: "claude",  label: "Claude",  sub: "by Anthropic", active: true  },
                        { id: "gemini",  label: "Gemini",  sub: "by Google",    active: false },
                        { id: "openai",  label: "GPT-4o",  sub: "by OpenAI",    active: false },
                      ] as { id: LLMModel; label: string; sub: string; active: boolean }[]
                    ).map((m) => (
                      <button
                        key={m.id}
                        disabled={!m.active}
                        onClick={() => m.active && setLlmModel(m.id)}
                        title={m.active ? undefined : "Coming soon — API key not configured"}
                        className={`flex-1 px-3 py-2.5 rounded-lg border text-left transition-all ${
                          !m.active
                            ? "border-border/20 opacity-35 cursor-not-allowed"
                            : llmModel === m.id
                              ? "border-primary/60 bg-primary/8 text-primary"
                              : "border-border/50 hover:border-border/80 text-muted-foreground"
                        }`}
                      >
                        <div className="text-xs font-semibold leading-none mb-0.5">{m.label}</div>
                        <div className="text-[10px] text-muted-foreground/50">{m.sub}</div>
                        {!m.active && (
                          <div className="text-[9px] text-muted-foreground/35 mt-0.5">Coming soon</div>
                        )}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Research query */}
                <div>
                  <p className="text-[10px] text-muted-foreground/60 uppercase tracking-widest mb-2">Research Query</p>
                  <textarea
                    value={llmQuery}
                    onChange={(e) => setLlmQuery(e.target.value)}
                    placeholder="What should the AI research?"
                    rows={5}
                    className="w-full bg-muted/40 border border-border/60 rounded-md px-3.5 py-3 text-sm text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50 resize-none"
                  />
                </div>

                {/* Optional context doc */}
                <div>
                  <p className="text-[10px] text-muted-foreground/60 uppercase tracking-widest mb-2">
                    Context Document <span className="normal-case text-muted-foreground/40">(optional)</span>
                  </p>
                  {llmContextFile ? (
                    <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-border/50 bg-muted/20">
                      <span className="shrink-0">{fileIcon(llmContextFile.name)}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-foreground truncate">{llmContextFile.name}</p>
                        <p className="text-[10px] text-muted-foreground/55">
                          {(llmContextFile.size / 1024).toFixed(1)} KB · used as AI context
                        </p>
                      </div>
                      <button
                        onClick={() => { setLlmContextFile(null); if (llmFileRef.current) llmFileRef.current.value = ""; }}
                        className="text-muted-foreground/40 hover:text-foreground transition-colors shrink-0"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => llmFileRef.current?.click()}
                      className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-lg border border-dashed border-border/50 text-xs text-muted-foreground/60 hover:text-foreground hover:border-primary/40 transition-all"
                    >
                      <Upload className="w-3 h-3" />
                      Attach a document for context
                    </button>
                  )}
                  <input
                    ref={llmFileRef}
                    type="file"
                    accept={ACCEPT}
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) setLlmContextFile(f);
                      e.target.value = "";
                    }}
                  />
                </div>

                {/* What you'll get */}
                <div className="rounded-lg border border-border/50 bg-muted/20 px-4 py-3 space-y-2">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-medium">What you'll get</p>
                  <div className="space-y-1.5 text-xs text-muted-foreground/80">
                    {[
                      ["🔍", "Query auto-categorised", "into Product / Market / Behavioural / Strategy"],
                      ["📄", "Full research paper", "1,500+ words, category-specific framework"],
                      ["📊", "Data & benchmarks",   "real numbers, historical analogues, risk estimates"],
                      ["🧠", "Ingested into KG",    "agents will debate and cite it directly"],
                    ].map(([icon, label, detail]) => (
                      <div key={label} className="flex items-start gap-1.5">
                        <span className="text-sm leading-none mt-0.5 shrink-0">{icon}</span>
                        <div>
                          <span className="font-medium text-foreground/80">{label}</span>
                          <span className="text-muted-foreground/55"> — {detail}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                  <p className="text-[10px] text-muted-foreground/40 pt-1">
                    Paper generation takes 30–60 seconds. Progress shown in the status indicator.
                  </p>
                </div>
              </div>
            )}

            {/* ── Feedback ── */}
            {error && (
              <p className="text-xs text-red-400 flex items-center gap-1.5">
                <span className="shrink-0">⚠</span> {error}
              </p>
            )}
            {success && (
              <div className="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/8 border border-emerald-500/20 rounded-md px-3.5 py-2.5">
                <CheckCircle className="w-3.5 h-3.5 shrink-0" />
                <span>{success} — redirecting to Agents…</span>
              </div>
            )}

            {/* ── Submit ── */}
            <button
              onClick={submit}
              disabled={!canSubmit}
              className="w-full bg-primary hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed text-primary-foreground font-medium py-2.5 rounded-md flex items-center justify-center gap-2 text-sm transition-colors"
            >
              {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {loading
                ? (ingestProgress || "Ingesting…")
                : tab === "llm-search"
                  ? "Generate Research Paper →"
                  : tab === "document"
                    ? selectedFiles.length > 1
                      ? `Ingest ${selectedFiles.length} files →`
                      : selectedFiles.length === 1 && isImageFile(selectedFiles[0].name)
                        ? "Analyse image & ingest →"
                        : "Ingest into knowledge graph →"
                    : "Ingest into knowledge graph →"
              }
            </button>

            {(session.status === "ready" || session.status === "simulating" || session.status === "complete") && (
              <button
                onClick={onGoToAgents}
                className="w-full border border-primary/30 text-primary hover:bg-primary/8 font-medium py-2 rounded-md text-xs transition-colors"
              >
                Skip — go to Agents →
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
