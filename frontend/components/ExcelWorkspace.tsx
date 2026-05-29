"use client";

import { useState, useRef, useEffect, ChangeEvent, DragEvent } from "react";
import * as XLSX from "xlsx";
import { 
  FileSpreadsheet, 
  Upload, 
  Trash2, 
  Filter, 
  Plus, 
  Download, 
  FileText, 
  Check, 
  AlertCircle,
  HelpCircle,
  Database,
  Globe
} from "lucide-react";

interface UploadedFile {
  id: string;
  name: string;
  size: number;
  headers: string[];
  rows: Record<string, any>[]; // Array of row objects
}

export default function ExcelWorkspace() {
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [activeFileId, setActiveFileId] = useState<string | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  // Load from localStorage on mount
  useEffect(() => {
    try {
      const savedFiles = localStorage.getItem("vergabepilot_excel_files");
      const savedActiveId = localStorage.getItem("vergabepilot_excel_active_id");
      if (savedFiles) {
        setUploadedFiles(JSON.parse(savedFiles));
      }
      if (savedActiveId) {
        setActiveFileId(savedActiveId);
      }
    } catch (e) {
      console.error("Failed to load Excel workspace files from localStorage:", e);
    }
    setIsLoaded(true);
  }, []);

  // Save to localStorage when files change
  useEffect(() => {
    if (!isLoaded) return;
    try {
      localStorage.setItem("vergabepilot_excel_files", JSON.stringify(uploadedFiles));
    } catch (e: any) {
      console.error("Failed to save Excel workspace files to localStorage:", e);
      if (e.name === "QuotaExceededError" || e.code === 22) {
        setErrorMsg("Storage quota exceeded. Spreadsheet data is too large to persist locally.");
      }
    }
  }, [uploadedFiles, isLoaded]);

  // Save active file ID to localStorage
  useEffect(() => {
    if (!isLoaded) return;
    try {
      if (activeFileId) {
        localStorage.setItem("vergabepilot_excel_active_id", activeFileId);
      } else {
        localStorage.removeItem("vergabepilot_excel_active_id");
      }
    } catch (e) {
      console.error("Failed to save active file ID to localStorage:", e);
    }
  }, [activeFileId, isLoaded]);
  
  // Table filters & editing state
  const [selectedDomain, setSelectedDomain] = useState<string>("ALL");
  const [editingCell, setEditingCell] = useState<{ rowIndex: number; columnKey: string } | null>(null);
  const [editValue, setEditValue] = useState<string>("");
  
  const [dragActive, setDragActive] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Active file details
  const activeFile = uploadedFiles.find(f => f.id === activeFileId) || null;

  // Process selected file
  const processFile = (file: File) => {
    setErrorMsg(null);
    const reader = new FileReader();
    
    reader.onload = (e) => {
      try {
        const data = e.target?.result;
        if (!data) throw new Error("Could not read file content");
        
        let workbook;
        if (file.name.endsWith(".csv")) {
          // Parse CSV
          workbook = XLSX.read(data, { type: "string" });
        } else {
          // Parse Binary Excel
          workbook = XLSX.read(data, { type: "binary" });
        }
        
        // Use the first worksheet
        const sheetName = workbook.SheetNames[0];
        const worksheet = workbook.Sheets[sheetName];
        
        // Parse rows as objects
        const rawRows = XLSX.utils.sheet_to_json(worksheet, { defval: "" }) as Record<string, any>[];
        
        if (rawRows.length === 0) {
          setErrorMsg(`Sheet "${file.name}" is empty or has no columns.`);
          return;
        }

        // Collect all unique headers/keys found across all rows
        const headersSet = new Set<string>();
        rawRows.forEach(row => {
          Object.keys(row).forEach(k => headersSet.add(k));
        });
        const headers = Array.from(headersSet);

        const newUploadedFile: UploadedFile = {
          id: `${Date.now()}-${file.name}`,
          name: file.name,
          size: file.size,
          headers,
          rows: rawRows
        };

        setUploadedFiles(prev => {
          const updated = [...prev, newUploadedFile];
          // Set as active if it is the first uploaded file
          if (updated.length === 1) {
            setActiveFileId(newUploadedFile.id);
          }
          return updated;
        });

      } catch (err: any) {
        console.error(err);
        setErrorMsg(`Failed to parse file: ${err.message || "Unknown error"}`);
      }
    };

    if (file.name.endsWith(".csv")) {
      reader.readAsText(file);
    } else {
      reader.readAsBinaryString(file);
    }
  };

  // Upload Handlers
  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      Array.from(e.target.files).forEach(file => processFile(file));
      // Reset input
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDrag = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      Array.from(e.dataTransfer.files).forEach(file => processFile(file));
    }
  };

  const deleteFile = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setUploadedFiles(prev => {
      const updated = prev.filter(f => f.id !== id);
      if (activeFileId === id) {
        setActiveFileId(updated.length > 0 ? updated[0].id : null);
      }
      return updated;
    });
  };

  // Helper: Extract domain from a URL string
  const extractDomain = (urlStr: any): string | null => {
    if (typeof urlStr !== "string") return null;
    const cleanStr = urlStr.trim();
    if (!cleanStr.startsWith("http://") && !cleanStr.startsWith("https://")) {
      // Check if it looks like a domain name anyway
      const domainPattern = /^([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,6}/;
      const match = cleanStr.match(domainPattern);
      return match ? match[0].toLowerCase() : null;
    }
    try {
      const parsed = new URL(cleanStr);
      return parsed.hostname.replace("www.", "").toLowerCase();
    } catch {
      return null;
    }
  };

  // Check columns containing URLs and extract unique domains
  const getUniqueDomains = (file: UploadedFile): string[] => {
    const domains = new Set<string>();
    file.rows.forEach(row => {
      Object.values(row).forEach(val => {
        const dom = extractDomain(val);
        if (dom) domains.add(dom);
      });
    });
    return Array.from(domains);
  };

  // Identify if a cell contains a URL/domain and return it
  const getCellDomain = (row: Record<string, any>): string | null => {
    for (const val of Object.values(row)) {
      const dom = extractDomain(val);
      if (dom) return dom;
    }
    return null;
  };

  // Filter Active File Rows
  const getFilteredRows = (): Record<string, any>[] => {
    if (!activeFile) return [];
    if (selectedDomain === "ALL") return activeFile.rows;
    return activeFile.rows.filter(row => getCellDomain(row) === selectedDomain);
  };

  // Inline Cell Editing
  const startEditing = (rowIndex: number, columnKey: string, currentValue: any) => {
    setEditingCell({ rowIndex, columnKey });
    setEditValue(String(currentValue ?? ""));
  };

  const saveCellEdit = () => {
    if (!editingCell || !activeFile) return;
    
    const { rowIndex, columnKey } = editingCell;
    const updatedFiles = uploadedFiles.map(file => {
      if (file.id === activeFile.id) {
        const newRows = [...file.rows];
        newRows[rowIndex] = {
          ...newRows[rowIndex],
          [columnKey]: editValue
        };
        return { ...file, rows: newRows };
      }
      return file;
    });

    setUploadedFiles(updatedFiles);
    setEditingCell(null);
  };

  // Add new row to active sheet
  const addRow = () => {
    if (!activeFile) return;
    const emptyRow: Record<string, any> = {};
    activeFile.headers.forEach(h => {
      emptyRow[h] = "";
    });

    const updatedFiles = uploadedFiles.map(file => {
      if (file.id === activeFile.id) {
        return {
          ...file,
          rows: [...file.rows, emptyRow]
        };
      }
      return file;
    });
    setUploadedFiles(updatedFiles);
  };

  // Add new column to active sheet
  const addColumn = () => {
    if (!activeFile) return;
    const colName = prompt("Enter new column name:");
    if (!colName || colName.trim() === "") return;
    const cleanColName = colName.trim();
    
    if (activeFile.headers.includes(cleanColName)) {
      alert("Column already exists!");
      return;
    }

    const updatedFiles = uploadedFiles.map(file => {
      if (file.id === activeFile.id) {
        const newRows = file.rows.map(row => ({
          ...row,
          [cleanColName]: ""
        }));
        return {
          ...file,
          headers: [...file.headers, cleanColName],
          rows: newRows
        };
      }
      return file;
    });
    setUploadedFiles(updatedFiles);
  };

  // Export current active sheet to XLSX
  const exportFile = () => {
    if (!activeFile) return;
    try {
      // Re-create worksheet from modified rows
      const worksheet = XLSX.utils.json_to_sheet(activeFile.rows);
      const workbook = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(workbook, worksheet, "Sheet1");
      
      // Save file
      const exportName = activeFile.name.replace(/\.[^/.]+$/, "") + "_modified.xlsx";
      XLSX.writeFile(workbook, exportName);
    } catch (err: any) {
      alert(`Failed to export file: ${err.message || "Unknown error"}`);
    }
  };

  // Format File Size
  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  return (
    <div className="bg-white border border-slate-200/80 rounded-3xl p-6 md:p-8 shadow-sm flex flex-col min-h-[600px] w-full transition-all duration-300">
      
      {/* 🟢 TOP AREA: Tab Header Description */}
      <div className="border-b border-slate-100 pb-5 mb-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-extrabold text-slate-800 flex items-center gap-2">
            <FileSpreadsheet className="w-6 h-6 text-indigo-500" />
            Interactive Excel/CSV Workspace
          </h2>
          <p className="text-xs text-slate-500 font-semibold mt-1">
            Upload multiple spreadsheets, edit rows inline, filter by target domains, and export modified sheets.
          </p>
        </div>
        
        {/* Error Alert Display */}
        {errorMsg && (
          <div className="flex items-center gap-2 px-4 py-2.5 bg-rose-50 border border-rose-150 rounded-xl text-rose-600 text-xs font-bold animate-fade-in">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}
      </div>

      {/* 🔵 WORKSPACE CONTAINER */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 flex-grow">
        
        {/* LEFT COLUMN: Uploader & Uploaded Sheets Directory */}
        <div className="lg:col-span-1 flex flex-col gap-6">
          
          {/* Uploader Box */}
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
            <div className={`p-3 rounded-full transition-colors ${dragActive ? 'bg-indigo-100 text-indigo-650' : 'bg-slate-100 text-slate-500'}`}>
              <Upload className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <p className="text-xs font-extrabold text-slate-700">Upload Spreadsheet</p>
              <p className="text-[10px] text-slate-400 font-semibold mt-1">Drag-and-drop or browse</p>
              <p className="text-[9px] text-slate-350 font-bold mt-0.5">Supports .xlsx, .xls, .csv</p>
            </div>
          </div>

          {/* Directory of Uploaded Sheets */}
          <div className="flex-grow flex flex-col bg-slate-50/55 border border-slate-150/60 rounded-2xl p-4 min-h-[250px]">
            <h3 className="text-xs font-extrabold text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Database className="w-3.5 h-3.5" />
              Sheets Library ({uploadedFiles.length})
            </h3>
            
            {uploadedFiles.length === 0 ? (
              <div className="flex-grow flex flex-col items-center justify-center text-center p-4">
                <FileText className="w-8 h-8 text-slate-300" />
                <p className="text-[11px] text-slate-400 font-semibold mt-2">No sheets uploaded yet.</p>
              </div>
            ) : (
              <ul className="space-y-2 overflow-y-auto max-h-[300px] pr-1 custom-scrollbar">
                {uploadedFiles.map(file => (
                  <li 
                    key={file.id}
                    onClick={() => {
                      setActiveFileId(file.id);
                      setSelectedDomain("ALL");
                      setEditingCell(null);
                    }}
                    className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-all active:scale-[0.98] ${
                      file.id === activeFileId
                        ? "bg-indigo-600 border-indigo-600 text-white shadow-sm shadow-indigo-600/10"
                        : "bg-white border-slate-100 text-slate-700 hover:border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <div className="min-w-0 flex items-center gap-2.5">
                      <FileSpreadsheet className={`w-4 h-4 flex-shrink-0 ${file.id === activeFileId ? 'text-white' : 'text-emerald-500'}`} />
                      <div className="min-w-0">
                        <p className="text-xs font-bold truncate">{file.name}</p>
                        <p className={`text-[10px] font-semibold truncate mt-0.5 ${file.id === activeFileId ? 'text-indigo-200' : 'text-slate-400'}`}>
                          {file.rows.length} rows • {formatBytes(file.size)}
                        </p>
                      </div>
                    </div>
                    
                    <button
                      onClick={(e) => deleteFile(file.id, e)}
                      className={`p-1.5 rounded-lg transition-colors flex-shrink-0 ${
                        file.id === activeFileId
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

        {/* RIGHT COLUMN: Interactive Spreadsheet Grid */}
        <div className="lg:col-span-3 flex flex-col bg-slate-50/30 border border-slate-200/50 rounded-3xl p-4 md:p-6 overflow-hidden min-h-[450px]">
          
          {!activeFile ? (
            <div className="flex-grow flex flex-col items-center justify-center text-center p-8 bg-white border border-slate-150/50 rounded-2xl">
              <div className="p-4 bg-indigo-50/50 text-indigo-500 rounded-full mb-3">
                <FileSpreadsheet className="w-10 h-10" />
              </div>
              <h3 className="text-md font-extrabold text-slate-700">No Worksheet Selected</h3>
              <p className="text-xs text-slate-400 font-semibold max-w-sm mt-1 leading-relaxed">
                Please upload an Excel or CSV file to start viewing, editing, and filtering your data.
              </p>
            </div>
          ) : (
            <div className="flex flex-col flex-grow overflow-hidden gap-5">
              
              {/* SHEET VIEW ACTIONS PANEL */}
              <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-4 border border-slate-150/70 rounded-2xl shadow-sm">
                
                {/* Domain Selector Filter */}
                <div className="flex items-center gap-2 min-w-[200px]">
                  <div className="p-1.5 bg-indigo-50 border border-indigo-100 rounded-lg text-indigo-600">
                    <Filter className="w-4 h-4" />
                  </div>
                  <div className="flex-grow">
                    <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-wider">Filter by Domain</label>
                    <select
                      value={selectedDomain}
                      onChange={(e) => {
                        setSelectedDomain(e.target.value);
                        setEditingCell(null);
                      }}
                      className="block w-full text-xs font-bold text-slate-700 mt-0.5 border-none bg-transparent focus:ring-0 p-0 cursor-pointer"
                    >
                      <option value="ALL">All Domains (No Filter)</option>
                      {getUniqueDomains(activeFile).map(dom => (
                        <option key={dom} value={dom}>{dom}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Spreadsheet controls & action buttons */}
                <div className="flex flex-wrap items-center gap-2.5">
                  
                  {/* Stats Badge */}
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-50 border border-slate-150/80 rounded-xl text-xs font-bold text-slate-500">
                    <Globe className="w-3.5 h-3.5 text-slate-400" />
                    Filtered: {getFilteredRows().length} / {activeFile.rows.length} rows
                  </span>

                  {/* Add Row Button */}
                  <button
                    onClick={addRow}
                    className="inline-flex items-center gap-1 px-3 py-1.5 bg-white border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50/10 text-xs font-bold text-slate-700 hover:text-indigo-650 rounded-xl transition-all"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Row
                  </button>

                  {/* Add Column Button */}
                  <button
                    onClick={addColumn}
                    className="inline-flex items-center gap-1 px-3 py-1.5 bg-white border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50/10 text-xs font-bold text-slate-700 hover:text-indigo-650 rounded-xl transition-all"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Col
                  </button>

                  {/* Export Button */}
                  <button
                    onClick={exportFile}
                    className="inline-flex items-center gap-1.5 px-4 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold rounded-xl shadow-sm hover:shadow active:scale-98 transition-all"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Export Sheet
                  </button>

                </div>
              </div>

              {/* DYNAMIC EDITABLE DATA GRID */}
              <div className="flex-grow overflow-auto border border-slate-200 rounded-2xl bg-white relative max-h-[480px]">
                <table className="min-w-full divide-y divide-slate-200 text-left text-xs border-collapse">
                  
                  {/* Grid Header */}
                  <thead className="bg-slate-50 sticky top-0 z-10 border-b border-slate-200">
                    <tr>
                      <th className="px-4 py-3 text-[10px] font-extrabold text-slate-400 uppercase tracking-wider w-12 text-center bg-slate-50 border-r border-slate-250">
                        #
                      </th>
                      {activeFile.headers.map(header => (
                        <th 
                          key={header} 
                          className="px-4 py-3 text-[10px] font-extrabold text-slate-500 uppercase tracking-wider font-mono border-r border-slate-200 bg-slate-50 truncate max-w-[200px]"
                        >
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  
                  {/* Grid Body */}
                  <tbody className="divide-y divide-slate-150 bg-white">
                    {getFilteredRows().length === 0 ? (
                      <tr>
                        <td 
                          colSpan={activeFile.headers.length + 1} 
                          className="px-6 py-10 text-center text-slate-400 font-semibold"
                        >
                          No rows match the selected domain filter.
                        </td>
                      </tr>
                    ) : (
                      getFilteredRows().map((row, relativeIndex) => {
                        // Find true index in the activeFile.rows array
                        const absoluteIndex = activeFile.rows.indexOf(row);
                        
                        return (
                          <tr key={absoluteIndex} className="hover:bg-slate-50/50 transition-colors">
                            
                            {/* Row Count Index */}
                            <td className="px-4 py-2.5 text-center font-mono font-bold text-slate-400 border-r border-slate-150 bg-slate-50/30">
                              {absoluteIndex + 1}
                            </td>

                            {/* Cells loop */}
                            {activeFile.headers.map(header => {
                              const cellValue = row[header];
                              const isEditing = editingCell?.rowIndex === absoluteIndex && editingCell?.columnKey === header;

                              return (
                                <td 
                                  key={header} 
                                  onClick={() => startEditing(absoluteIndex, header, cellValue)}
                                  className={`px-4 py-2.5 border-r border-slate-150 cursor-pointer min-w-[150px] max-w-[300px] truncate transition-colors relative ${
                                    isEditing ? "bg-indigo-50/30 p-1" : "hover:bg-indigo-50/10"
                                  }`}
                                >
                                  {isEditing ? (
                                    <input
                                      type="text"
                                      autoFocus
                                      value={editValue}
                                      onChange={(e) => setEditValue(e.target.value)}
                                      onBlur={saveCellEdit}
                                      onKeyDown={(e) => {
                                        if (e.key === "Enter") saveCellEdit();
                                        if (e.key === "Escape") setEditingCell(null);
                                      }}
                                      className="w-full text-xs px-2.5 py-1 bg-white border border-indigo-300 rounded-lg focus:ring-1 focus:ring-indigo-500 focus:outline-none font-medium"
                                    />
                                  ) : (
                                    <span className="font-semibold text-slate-700">
                                      {cellValue === "" ? (
                                        <span className="text-slate-350 italic font-bold">empty</span>
                                      ) : (
                                        cellValue
                                      )}
                                    </span>
                                  )}
                                </td>
                              );
                            })}

                          </tr>
                        );
                      })
                    )}
                  </tbody>

                </table>
              </div>

              {/* MICRO FOOTER / INTERACTION GUIDE */}
              <div className="text-[10px] text-slate-400 font-bold flex items-center justify-center gap-1">
                <HelpCircle className="w-3.5 h-3.5" />
                <span>💡 Tip: Double-click any table cell to edit its value inline. Press Enter or click outside to save.</span>
              </div>

            </div>
          )}

        </div>

      </div>

    </div>
  );
}
