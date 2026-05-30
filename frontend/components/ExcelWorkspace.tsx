"use client";

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
  ChangeEvent,
  DragEvent,
  memo,
} from "react";
import * as XLSX from "xlsx";
import { List } from "react-window";
import {
  FileSpreadsheet,
  Upload,
  Trash2,
  Filter,
  Plus,
  Download,
  FileText,
  AlertCircle,
  HelpCircle,
  Database,
  Globe,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────
interface UploadedFile {
  id: string;
  name: string;
  size: number;
  headers: string[];
  rows: Record<string, any>[];
}

interface RowProps {
  filteredRows: { row: Record<string, any>; absoluteIndex: number }[];
  headers: string[];
  editingRowIndex: number | null;
  editingColumnKey: string | null;
  onStartEdit: (rowIndex: number, columnKey: string) => void;
  onSaveEdit: (rowIndex: number, columnKey: string, value: string) => void;
  onCancelEdit: () => void;
}

// ─── IndexedDB Helpers ───────────────────────────────────────────────
const DB_NAME = "VergabepilotExcelDB";
const STORE_NAME = "excel_files";
let dbPromise: Promise<IDBDatabase> | null = null;

function getDB(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (typeof window === "undefined" || !window.indexedDB) {
      reject(new Error("IndexedDB not supported"));
      return;
    }
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      dbPromise = null;
      reject(request.error);
    };
  });
  return dbPromise;
}

function setDBItem(key: string, value: any): Promise<void> {
  return getDB().then(
    (db) =>
      new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readwrite");
        const store = tx.objectStore(STORE_NAME);
        const req = store.put(value, key);
        req.onsuccess = () => resolve();
        req.onerror = () => reject(req.error);
      })
  );
}

function getDBItem<T>(key: string): Promise<T | null> {
  return getDB().then(
    (db) =>
      new Promise<T | null>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readonly");
        const store = tx.objectStore(STORE_NAME);
        const req = store.get(key);
        req.onsuccess = () => resolve((req.result as T) || null);
        req.onerror = () => reject(req.error);
      })
  );
}

function removeDBItem(key: string): Promise<void> {
  return getDB().then(
    (db) =>
      new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readwrite");
        const store = tx.objectStore(STORE_NAME);
        const req = store.delete(key);
        req.onsuccess = () => resolve();
        req.onerror = () => reject(req.error);
      })
  );
}

// ─── Pure Helpers ────────────────────────────────────────────────────
function extractDomain(urlStr: any): string | null {
  if (typeof urlStr !== "string") return null;
  const s = urlStr.trim();
  if (!s.startsWith("http://") && !s.startsWith("https://")) {
    const m = s.match(/^([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,6}/);
    return m ? m[0].toLowerCase() : null;
  }
  try {
    return new URL(s).hostname.replace("www.", "").toLowerCase();
  } catch {
    return null;
  }
}

function getCellDomain(row: Record<string, any>): string | null {
  for (const val of Object.values(row)) {
    const d = extractDomain(val);
    if (d) return d;
  }
  return null;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

// ─── Virtualized Row Component (compatible with react-window v2) ─────
const VirtualRow = memo(function VirtualRow({
  index,
  style,
  filteredRows,
  headers,
  editingRowIndex,
  editingColumnKey,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
}: {
  index: number;
  style: React.CSSProperties;
} & RowProps) {
  const { row, absoluteIndex } = filteredRows[index];
  const inputRef = useRef<HTMLInputElement>(null);

  const isEditingThisRow = editingRowIndex === absoluteIndex;

  return (
    <div
      style={style}
      className={`flex border-b border-slate-100 ${
        index % 2 === 0 ? "bg-white" : "bg-slate-50/30"
      }`}
    >
      {/* Row # */}
      <div className="flex-shrink-0 w-14 px-2 flex items-center justify-center font-mono text-[11px] font-bold text-slate-400 border-r border-slate-150 bg-slate-50/40">
        {absoluteIndex + 1}
      </div>

      {/* Cells */}
      {headers.map((header) => {
        const cellValue = row[header];
        const isEditing =
          isEditingThisRow && editingColumnKey === header;

        return (
          <div
            key={header}
            onClick={() => {
              if (!isEditing) onStartEdit(absoluteIndex, header);
            }}
            className={`flex-shrink-0 w-[180px] px-3 flex items-center border-r border-slate-100 cursor-pointer truncate text-xs ${
              isEditing ? "bg-indigo-50/50" : "hover:bg-blue-50/30"
            }`}
          >
            {isEditing ? (
              <input
                ref={inputRef}
                type="text"
                autoFocus
                defaultValue={String(cellValue ?? "")}
                onBlur={() => {
                  onSaveEdit(
                    absoluteIndex,
                    header,
                    inputRef.current?.value ?? ""
                  );
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    onSaveEdit(
                      absoluteIndex,
                      header,
                      inputRef.current?.value ?? ""
                    );
                  } else if (e.key === "Escape") {
                    onCancelEdit();
                  }
                }}
                onClick={(e) => e.stopPropagation()}
                className="w-full text-xs px-2 py-0.5 bg-white border border-indigo-300 rounded-md focus:ring-1 focus:ring-indigo-500 focus:outline-none font-medium"
              />
            ) : (
              <span className="font-medium text-slate-700 truncate">
                {cellValue === "" ||
                cellValue === null ||
                cellValue === undefined ? (
                  <span className="text-slate-300 italic text-[10px]">
                    —
                  </span>
                ) : (
                  String(cellValue)
                )}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
});

// ─── Main Component ──────────────────────────────────────────────────
export default function ExcelWorkspace() {
  const filesRef = useRef<UploadedFile[]>([]);
  const [dataVersion, setDataVersion] = useState(0);
  const [fileIds, setFileIds] = useState<string[]>([]);
  const [activeFileId, setActiveFileId] = useState<string | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  const [selectedDomain, setSelectedDomain] = useState<string>("ALL");
  const [editingRowIndex, setEditingRowIndex] = useState<number | null>(null);
  const [editingColumnKey, setEditingColumnKey] = useState<string | null>(null);

  const [dragActive, setDragActive] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const gridContainerRef = useRef<HTMLDivElement>(null);
  const [gridHeight, setGridHeight] = useState(420);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ─── Measure grid height ──────────────────────────────────────────
  useEffect(() => {
    const el = gridContainerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setGridHeight(Math.max(200, Math.floor(e.contentRect.height) - 4));
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ─── IndexedDB load ───────────────────────────────────────────────
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const saved = await getDBItem<UploadedFile[]>(
          "vergabepilot_excel_files"
        );
        const savedId = await getDBItem<string>(
          "vergabepilot_excel_active_id"
        );
        if (!active) return;
        if (saved) {
          filesRef.current = saved;
          setFileIds(saved.map((f) => f.id));
          setDataVersion((v) => v + 1);
        }
        if (savedId) setActiveFileId(savedId);
      } catch (e) {
        console.error("IndexedDB load failed:", e);
      } finally {
        if (active) setIsLoaded(true);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  // ─── Debounced save to IndexedDB ──────────────────────────────────
  const scheduleSave = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      try {
        await setDBItem("vergabepilot_excel_files", filesRef.current);
        setErrorMsg(null);
      } catch (e: any) {
        console.error("IndexedDB save failed:", e);
        setErrorMsg("Failed to persist data locally.");
      }
    }, 1000);
  }, []);

  // Save active file ID
  useEffect(() => {
    if (!isLoaded) return;
    if (activeFileId) {
      setDBItem("vergabepilot_excel_active_id", activeFileId).catch(() => {});
    } else {
      removeDBItem("vergabepilot_excel_active_id").catch(() => {});
    }
  }, [activeFileId, isLoaded]);

  // ─── Derived data ─────────────────────────────────────────────────
  const fileSummaries = useMemo(() => {
    const _v = dataVersion;
    return filesRef.current.map((f) => ({
      id: f.id,
      name: f.name,
      size: f.size,
      rowCount: f.rows.length,
    }));
  }, [dataVersion]);

  const activeFile = useMemo(() => {
    const _v = dataVersion;
    return filesRef.current.find((f) => f.id === activeFileId) || null;
  }, [activeFileId, dataVersion]);

  const uniqueDomains = useMemo(() => {
    if (!activeFile) return [];
    const set = new Set<string>();
    for (const row of activeFile.rows) {
      for (const val of Object.values(row)) {
        const d = extractDomain(val);
        if (d) set.add(d);
      }
    }
    return Array.from(set).sort();
  }, [activeFile]);

  const filteredRows = useMemo(() => {
    if (!activeFile) return [];
    if (selectedDomain === "ALL") {
      return activeFile.rows.map((row, i) => ({ row, absoluteIndex: i }));
    }
    const result: { row: Record<string, any>; absoluteIndex: number }[] = [];
    for (let i = 0; i < activeFile.rows.length; i++) {
      if (getCellDomain(activeFile.rows[i]) === selectedDomain) {
        result.push({ row: activeFile.rows[i], absoluteIndex: i });
      }
    }
    return result;
  }, [activeFile, selectedDomain]);

  // ─── File processing ──────────────────────────────────────────────
  const processFile = useCallback(
    (file: File) => {
      setErrorMsg(null);
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const data = e.target?.result;
          if (!data) throw new Error("Could not read file");
          const wb = XLSX.read(data, {
            type: file.name.endsWith(".csv") ? "string" : "binary",
          });
          const ws = wb.Sheets[wb.SheetNames[0]];
          const rawRows = XLSX.utils.sheet_to_json(ws, {
            defval: "",
          }) as Record<string, any>[];

          if (rawRows.length === 0) {
            setErrorMsg(`"${file.name}" is empty.`);
            return;
          }

          const headersSet = new Set<string>();
          rawRows.forEach((r) => Object.keys(r).forEach((k) => headersSet.add(k)));

          const newFile: UploadedFile = {
            id: `${Date.now()}-${file.name}`,
            name: file.name,
            size: file.size,
            headers: Array.from(headersSet),
            rows: rawRows,
          };

          filesRef.current = [...filesRef.current, newFile];
          setFileIds(filesRef.current.map((f) => f.id));
          if (filesRef.current.length === 1) setActiveFileId(newFile.id);
          setDataVersion((v) => v + 1);
          scheduleSave();
        } catch (err: any) {
          setErrorMsg(`Parse failed: ${err.message || "Unknown error"}`);
        }
      };
      if (file.name.endsWith(".csv")) reader.readAsText(file);
      else reader.readAsBinaryString(file);
    },
    [scheduleSave]
  );

  const handleFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        Array.from(e.target.files).forEach(processFile);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    },
    [processFile]
  );

  const handleDrag = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(e.type === "dragenter" || e.type === "dragover");
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);
      if (e.dataTransfer.files) {
        Array.from(e.dataTransfer.files).forEach(processFile);
      }
    },
    [processFile]
  );

  const deleteFile = useCallback(
    (id: string, e: React.MouseEvent) => {
      e.stopPropagation();
      filesRef.current = filesRef.current.filter((f) => f.id !== id);
      setFileIds(filesRef.current.map((f) => f.id));
      if (activeFileId === id) {
        setActiveFileId(
          filesRef.current.length > 0 ? filesRef.current[0].id : null
        );
      }
      setDataVersion((v) => v + 1);
      scheduleSave();
    },
    [activeFileId, scheduleSave]
  );

  // ─── Cell editing ──────────────────────────────────────────────────
  const onStartEdit = useCallback(
    (rowIndex: number, columnKey: string) => {
      setEditingRowIndex(rowIndex);
      setEditingColumnKey(columnKey);
    },
    []
  );

  const onSaveEdit = useCallback(
    (rowIndex: number, columnKey: string, value: string) => {
      const file = filesRef.current.find((f) => f.id === activeFileId);
      if (file && file.rows[rowIndex]) {
        file.rows[rowIndex][columnKey] = value;
        setDataVersion((v) => v + 1);
        scheduleSave();
      }
      setEditingRowIndex(null);
      setEditingColumnKey(null);
    },
    [activeFileId, scheduleSave]
  );

  const onCancelEdit = useCallback(() => {
    setEditingRowIndex(null);
    setEditingColumnKey(null);
  }, []);

  const addRow = useCallback(() => {
    const file = filesRef.current.find((f) => f.id === activeFileId);
    if (!file) return;
    const emptyRow: Record<string, any> = {};
    file.headers.forEach((h) => (emptyRow[h] = ""));
    file.rows.push(emptyRow);
    setDataVersion((v) => v + 1);
    scheduleSave();
  }, [activeFileId, scheduleSave]);

  const addColumn = useCallback(() => {
    const file = filesRef.current.find((f) => f.id === activeFileId);
    if (!file) return;
    const colName = prompt("Enter new column name:");
    if (!colName?.trim()) return;
    const clean = colName.trim();
    if (file.headers.includes(clean)) {
      alert("Column already exists!");
      return;
    }
    file.headers.push(clean);
    for (const row of file.rows) {
      row[clean] = "";
    }
    setDataVersion((v) => v + 1);
    scheduleSave();
  }, [activeFileId, scheduleSave]);

  const exportFile = useCallback(() => {
    if (!activeFile) return;
    try {
      const ws = XLSX.utils.json_to_sheet(activeFile.rows);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
      XLSX.writeFile(
        wb,
        activeFile.name.replace(/\.[^/.]+$/, "") + "_modified.xlsx"
      );
    } catch (err: any) {
      alert(`Export failed: ${err.message}`);
    }
  }, [activeFile]);

  // ─── react-window props ───────────────────────────────────────────
  const rowProps: RowProps = useMemo(
    () => ({
      filteredRows,
      headers: activeFile?.headers || [],
      editingRowIndex,
      editingColumnKey,
      onStartEdit,
      onSaveEdit,
      onCancelEdit,
    }),
    [
      filteredRows,
      activeFile?.headers,
      editingRowIndex,
      editingColumnKey,
      onStartEdit,
      onSaveEdit,
      onCancelEdit,
    ]
  );

  // ─── Layout constants ─────────────────────────────────────────────
  const COL_W = 180;
  const ROW_NUM_W = 56;
  const totalW = activeFile
    ? ROW_NUM_W + activeFile.headers.length * COL_W
    : 0;

  // ─── Render ────────────────────────────────────────────────────────
  return (
    <div className="bg-white border border-slate-200/80 rounded-3xl p-6 md:p-8 shadow-sm flex flex-col min-h-[600px] w-full">
      {/* Header */}
      <div className="border-b border-slate-100 pb-5 mb-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-extrabold text-slate-800 flex items-center gap-2">
            <FileSpreadsheet className="w-6 h-6 text-indigo-500" />
            Interactive Excel/CSV Workspace
          </h2>
          <p className="text-xs text-slate-500 font-semibold mt-1">
            Upload spreadsheets, edit inline, filter by domain, and export.
          </p>
        </div>
        {errorMsg && (
          <div className="flex items-center gap-2 px-4 py-2.5 bg-rose-50 border border-rose-200 rounded-xl text-rose-600 text-xs font-bold">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}
      </div>

      {/* Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 flex-grow">
        {/* LEFT: Upload & File List */}
        <div className="lg:col-span-1 flex flex-col gap-6">
          {/* Upload */}
          <div
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-2xl p-6 text-center cursor-pointer transition-all duration-200 flex flex-col items-center justify-center gap-2.5 ${
              dragActive
                ? "border-indigo-500 bg-indigo-50/40 shadow-sm"
                : "border-slate-200 hover:border-indigo-400 hover:bg-slate-50/50"
            }`}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              accept=".xlsx,.xls,.csv"
              multiple
              className="hidden"
            />
            <div
              className={`p-3 rounded-full ${
                dragActive
                  ? "bg-indigo-100 text-indigo-600"
                  : "bg-slate-100 text-slate-500"
              }`}
            >
              <Upload className="w-5 h-5" />
            </div>
            <div>
              <p className="text-xs font-extrabold text-slate-700">
                Upload Spreadsheet
              </p>
              <p className="text-[10px] text-slate-400 font-semibold mt-1">
                Drag-and-drop or browse
              </p>
              <p className="text-[9px] text-slate-350 font-bold mt-0.5">
                .xlsx, .xls, .csv
              </p>
            </div>
          </div>

          {/* File list */}
          <div className="flex-grow flex flex-col bg-slate-50/55 border border-slate-150/60 rounded-2xl p-4 min-h-[250px]">
            <h3 className="text-xs font-extrabold text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Database className="w-3.5 h-3.5" />
              Sheets ({fileSummaries.length})
            </h3>
            {fileSummaries.length === 0 ? (
              <div className="flex-grow flex flex-col items-center justify-center text-center p-4">
                <FileText className="w-8 h-8 text-slate-300" />
                <p className="text-[11px] text-slate-400 font-semibold mt-2">
                  No sheets uploaded yet.
                </p>
              </div>
            ) : (
              <ul className="space-y-2 overflow-y-auto max-h-[300px] pr-1">
                {fileSummaries.map((fs) => (
                  <li
                    key={fs.id}
                    onClick={() => {
                      setActiveFileId(fs.id);
                      setSelectedDomain("ALL");
                      setEditingRowIndex(null);
                      setEditingColumnKey(null);
                    }}
                    className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-all active:scale-[0.98] ${
                      fs.id === activeFileId
                        ? "bg-indigo-600 border-indigo-600 text-white shadow-sm"
                        : "bg-white border-slate-100 text-slate-700 hover:border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <div className="min-w-0 flex items-center gap-2.5">
                      <FileSpreadsheet
                        className={`w-4 h-4 flex-shrink-0 ${
                          fs.id === activeFileId
                            ? "text-white"
                            : "text-emerald-500"
                        }`}
                      />
                      <div className="min-w-0">
                        <p className="text-xs font-bold truncate">{fs.name}</p>
                        <p
                          className={`text-[10px] font-semibold truncate mt-0.5 ${
                            fs.id === activeFileId
                              ? "text-indigo-200"
                              : "text-slate-400"
                          }`}
                        >
                          {fs.rowCount} rows • {formatBytes(fs.size)}
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={(e) => deleteFile(fs.id, e)}
                      className={`p-1.5 rounded-lg flex-shrink-0 ${
                        fs.id === activeFileId
                          ? "hover:bg-indigo-700 text-indigo-200 hover:text-white"
                          : "hover:bg-rose-50 text-slate-400 hover:text-rose-500"
                      }`}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* RIGHT: Data Grid */}
        <div className="lg:col-span-3 flex flex-col bg-slate-50/30 border border-slate-200/50 rounded-3xl p-4 md:p-6 overflow-hidden min-h-[450px]">
          {!activeFile ? (
            <div className="flex-grow flex flex-col items-center justify-center text-center p-8 bg-white border border-slate-150/50 rounded-2xl">
              <div className="p-4 bg-indigo-50/50 text-indigo-500 rounded-full mb-3">
                <FileSpreadsheet className="w-10 h-10" />
              </div>
              <h3 className="text-md font-extrabold text-slate-700">
                No Worksheet Selected
              </h3>
              <p className="text-xs text-slate-400 font-semibold max-w-sm mt-1 leading-relaxed">
                Upload an Excel or CSV file to start viewing, editing, and
                filtering your data.
              </p>
            </div>
          ) : (
            <div className="flex flex-col flex-grow overflow-hidden gap-5">
              {/* Actions panel */}
              <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-4 border border-slate-150/70 rounded-2xl shadow-sm flex-shrink-0">
                <div className="flex items-center gap-2 min-w-[200px]">
                  <div className="p-1.5 bg-indigo-50 border border-indigo-100 rounded-lg text-indigo-600">
                    <Filter className="w-4 h-4" />
                  </div>
                  <div className="flex-grow">
                    <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                      Filter by Domain
                    </label>
                    <select
                      value={selectedDomain}
                      onChange={(e) => {
                        setSelectedDomain(e.target.value);
                        setEditingRowIndex(null);
                        setEditingColumnKey(null);
                      }}
                      className="block w-full text-xs font-bold text-slate-700 mt-0.5 border-none bg-transparent focus:ring-0 p-0 cursor-pointer"
                    >
                      <option value="ALL">All Domains</option>
                      {uniqueDomains.map((d) => (
                        <option key={d} value={d}>
                          {d}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2.5">
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-50 border border-slate-150/80 rounded-xl text-xs font-bold text-slate-500">
                    <Globe className="w-3.5 h-3.5 text-slate-400" />
                    {filteredRows.length} / {activeFile.rows.length} rows
                  </span>
                  <button
                    onClick={addRow}
                    className="inline-flex items-center gap-1 px-3 py-1.5 bg-white border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50/10 text-xs font-bold text-slate-700 rounded-xl transition-colors"
                  >
                    <Plus className="w-3.5 h-3.5" /> Row
                  </button>
                  <button
                    onClick={addColumn}
                    className="inline-flex items-center gap-1 px-3 py-1.5 bg-white border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50/10 text-xs font-bold text-slate-700 rounded-xl transition-colors"
                  >
                    <Plus className="w-3.5 h-3.5" /> Col
                  </button>
                  <button
                    onClick={exportFile}
                    className="inline-flex items-center gap-1.5 px-4 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold rounded-xl shadow-sm transition-colors"
                  >
                    <Download className="w-3.5 h-3.5" /> Export
                  </button>
                </div>
              </div>

              {/* Virtualized grid */}
              <div
                ref={gridContainerRef}
                className="flex-grow overflow-hidden border border-slate-200 rounded-2xl bg-white relative"
              >
                <div className="overflow-x-auto h-full">
                  <div style={{ minWidth: totalW }}>
                    {/* Sticky header */}
                    <div className="flex bg-slate-50 border-b border-slate-200 sticky top-0 z-10">
                      <div className="flex-shrink-0 w-14 px-2 py-3 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider text-center border-r border-slate-200 bg-slate-50">
                        #
                      </div>
                      {activeFile.headers.map((h) => (
                        <div
                          key={h}
                          className="flex-shrink-0 w-[180px] px-3 py-3 text-[10px] font-extrabold text-slate-500 uppercase tracking-wider font-mono border-r border-slate-200 bg-slate-50 truncate"
                        >
                          {h}
                        </div>
                      ))}
                    </div>

                    {/* Rows */}
                    {filteredRows.length === 0 ? (
                      <div className="px-6 py-10 text-center text-slate-400 font-semibold text-sm">
                        No rows match the selected filter.
                      </div>
                    ) : (
                      <List
                        style={{ height: gridHeight - 44 }}
                        rowCount={filteredRows.length}
                        rowHeight={38}
                        rowComponent={VirtualRow as any}
                        rowProps={rowProps}
                        overscanCount={8}
                      />
                    )}
                  </div>
                </div>
              </div>

              <div className="text-[10px] text-slate-400 font-bold flex items-center justify-center gap-1 flex-shrink-0">
                <HelpCircle className="w-3.5 h-3.5" />
                <span>
                  Click any cell to edit · Enter to save · Escape to cancel
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
