import {
  type ColumnDef,
  type ColumnFiltersState,
  type RowSelectionState,
  type SortingState,
  type VisibilityState,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import {
  DataTableRowActions,
  DataTableRowSelectionCell,
  DataTableRowSelectionHeader,
  DataTableShell,
  DataTableSortableHeader,
  DataTableToolbar,
  DataTableViewOptions,
} from '@/components/data-table'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  createNamingTemplate,
  createSavedView,
  deleteSavedView,
  getJob,
  getManifestConflicts,
  getManifestRows,
  listNamingTemplates,
  listSavedViews,
  patchManifestRows,
} from '@/lib/api'
import { RuleStudioSheet } from '@/components/review/rule-studio-sheet'
import { useI18n } from '@/lib/i18n'
import type { Job, ManifestConflict, ManifestRow, ManifestRowPatch, NamingTemplate, SavedView } from '@/lib/types'
import { createRouteIntentPrefetchHandlers } from '@/routes/lazy-routes'

const ConflictCenter = lazy(() => import('@/components/manifest/conflict-center').then((module) => ({ default: module.ConflictCenter })))
const PreviewDrawer = lazy(() => import('@/components/manifest/preview-drawer').then((module) => ({ default: module.PreviewDrawer })))

const defaultColumns: VisibilityState = {
  media_type: true,
  category: true,
  title: true,
  tags: true,
  status: true,
  error_code: true,
  target_suggestion: true,
  notes: true,
  ignore: true,
  confidence: true,
  conflict_state: false,
}

function buildPatch(base: ManifestRow, edited: ManifestRow): ManifestRowPatch | null {
  const patch: ManifestRowPatch = { row_id: base.id }
  let changed = false

  if (base.category !== edited.category) {
    patch.category = edited.category
    changed = true
  }
  if (base.title !== edited.title) {
    patch.title = edited.title
    changed = true
  }
  if (base.tags.join('|') !== edited.tags.join('|')) {
    patch.tags = edited.tags
    changed = true
  }
  if (base.notes !== edited.notes) {
    patch.notes = edited.notes
    changed = true
  }
  if (base.target_suggestion !== edited.target_suggestion) {
    patch.target_suggestion = edited.target_suggestion
    changed = true
  }
  if (base.ignore !== edited.ignore) {
    patch.ignore = edited.ignore
    changed = true
  }

  return changed ? patch : null
}

function applyTemplatePattern(template: NamingTemplate, row: ManifestRow): string {
  const date = row.metadata.exif_datetime || row.metadata.file_mtime || new Date().toISOString().slice(0, 10)
  const hash8 = row.id.slice(-8)
  return template.pattern
    .replaceAll('{date}', date.slice(0, 10))
    .replaceAll('{category}', row.category)
    .replaceAll('{title}', row.title)
    .replaceAll('{hash8}', hash8)
    .replaceAll('{project}', 'fileorganize')
}

function FeatureCardFallback({ title }: { title: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Skeleton className="h-9 w-full rounded-xl" />
        <Skeleton className="h-16 w-full rounded-xl" />
        <Skeleton className="h-16 w-full rounded-xl" />
      </CardContent>
    </Card>
  )
}

function PreviewDrawerFallback() {
  return <FeatureCardFallback title="Preview Drawer Loading..." />
}

export function ManifestPage() {
  const { t } = useI18n()
  const { jobId = '' } = useParams()
  const [job, setJob] = useState<Job | null>(null)
  const [manifestRows, setManifestRows] = useState<ManifestRow[]>([])
  const [conflicts, setConflicts] = useState<ManifestConflict[]>([])
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [conflictFilter, setConflictFilter] = useState<'all' | 'open' | 'error_only'>('all')
  const [editedMap, setEditedMap] = useState<Record<string, ManifestRow>>({})
  const [previewRowId, setPreviewRowId] = useState('')
  const [savedViews, setSavedViews] = useState<SavedView[]>([])
  const [viewName, setViewName] = useState('')
  const [templates, setTemplates] = useState<NamingTemplate[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [newTemplateName, setNewTemplateName] = useState('')
  const [newTemplatePattern, setNewTemplatePattern] = useState('{category}/{title}__{hash8}')
  const [batchCategory, setBatchCategory] = useState('')
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(defaultColumns)
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})

  const refreshAll = async () => {
    try {
      const [nextJob, nextRows, nextConflicts, nextViews, nextTemplates] = await Promise.all([
        getJob(jobId),
        getManifestRows(jobId),
        getManifestConflicts(jobId),
        listSavedViews('manifest'),
        listNamingTemplates(),
      ])
      setJob(nextJob ?? null)
      setManifestRows(nextRows)
      setConflicts(nextConflicts)
      setSavedViews(nextViews)
      setTemplates(nextTemplates)
      setSelectedTemplateId((prev) => prev || nextTemplates[0]?.id || '')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'The manifest workspace could not be refreshed.')
    }
  }

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const [nextJob, nextRows, nextConflicts, nextViews, nextTemplates] = await Promise.all([
          getJob(jobId),
          getManifestRows(jobId),
          getManifestConflicts(jobId),
          listSavedViews('manifest'),
          listNamingTemplates(),
        ])
        if (!alive) {
          return
        }
        setJob(nextJob ?? null)
        setManifestRows(nextRows)
        setConflicts(nextConflicts)
        setSavedViews(nextViews)
        setTemplates(nextTemplates)
        setSelectedTemplateId((prev) => prev || nextTemplates[0]?.id || '')
      } catch (error) {
        if (!alive) {
          return
        }
        setManifestRows([])
        setConflicts([])
        setSavedViews([])
        setTemplates([])
        toast.error(error instanceof Error ? error.message : 'The manifest workspace could not be loaded.')
      }
    })()

    return () => {
      alive = false
    }
  }, [jobId])

  const effectiveRows = useMemo(() => {
    return manifestRows.map((row) => editedMap[row.id] ?? row)
  }, [editedMap, manifestRows])

  const conflictRowSet = useMemo(() => {
    return new Set(conflicts.filter((item) => item.status === 'open').map((item) => item.row_id))
  }, [conflicts])

  useEffect(() => {
    setColumnFilters((prev) => {
      const next = prev.filter((item) => item.id !== 'status' && item.id !== 'conflict_state')
      if (statusFilter !== 'all') {
        next.push({ id: 'status', value: statusFilter })
      }
      if (conflictFilter !== 'all') {
        next.push({ id: 'conflict_state', value: conflictFilter })
      }
      return next
    })
  }, [conflictFilter, statusFilter])

  useEffect(() => {
    setRowSelection((prev) => {
      const validIds = new Set(effectiveRows.map((row) => row.id))
      let changed = false
      const next: RowSelectionState = {}
      for (const [rowId, selected] of Object.entries(prev)) {
        if (selected && validIds.has(rowId)) {
          next[rowId] = true
          continue
        }
        changed = true
      }
      return changed ? next : prev
    })
  }, [effectiveRows])

  const updateRow = useCallback(
    (rowId: string, updater: (row: ManifestRow) => ManifestRow) => {
      const base = effectiveRows.find((item) => item.id === rowId)
      if (!base) {
        return
      }
      setEditedMap((prev) => ({
        ...prev,
        [rowId]: updater(base),
      }))
    },
    [effectiveRows],
  )

  const columns = useMemo<ColumnDef<ManifestRow>[]>(
    () => [
      {
        id: 'select',
        enableSorting: false,
        enableHiding: false,
        header: ({ table }) => <DataTableRowSelectionHeader ariaLabel="Select all rows" table={table} usePageRows={false} />,
        cell: ({ row }) => <DataTableRowSelectionCell ariaLabel={`Select ${row.original.file_name}`} row={row} />,
        meta: {
          headerClassName: 'sticky left-0 z-20 w-10 bg-card',
          cellClassName: 'sticky left-0 z-10 bg-card',
        },
      },
      {
        accessorKey: 'file_name',
        enableHiding: false,
        header: ({ column }) => (
          <DataTableSortableHeader label="Filename" onToggle={() => column.toggleSorting(column.getIsSorted() === 'asc')} sorted={column.getIsSorted()} />
        ),
        cell: ({ row }) => {
          const data = row.original
          const hasConflict = conflictRowSet.has(data.id) || data.status === 'error' || data.status === 'duplicate'
          return (
            <div className="max-w-[240px]">
              <p className="truncate font-medium">{data.file_name}</p>
              {hasConflict ? <Badge variant="warning">Conflict</Badge> : null}
            </div>
          )
        },
        meta: {
          headerClassName: 'sticky left-10 z-20 min-w-[190px] bg-card',
          cellClassName: 'sticky left-10 z-10 bg-card',
        },
      },
      {
        accessorKey: 'media_type',
        header: ({ column }) => (
          <DataTableSortableHeader label="Media Type" onToggle={() => column.toggleSorting(column.getIsSorted() === 'asc')} sorted={column.getIsSorted()} />
        ),
      },
      {
        accessorKey: 'category',
        header: ({ column }) => (
          <DataTableSortableHeader label="Category" onToggle={() => column.toggleSorting(column.getIsSorted() === 'asc')} sorted={column.getIsSorted()} />
        ),
        cell: ({ row }) => (
          <Input
            aria-label={`Edit category for ${row.original.file_name}`}
            className="h-8"
            onChange={(event) =>
              updateRow(row.original.id, (next) => ({
                ...next,
                category: event.target.value,
              }))
            }
            onClick={(event) => event.stopPropagation()}
            value={row.original.category}
          />
        ),
      },
      {
        accessorKey: 'title',
        header: ({ column }) => (
          <DataTableSortableHeader label="Title" onToggle={() => column.toggleSorting(column.getIsSorted() === 'asc')} sorted={column.getIsSorted()} />
        ),
        cell: ({ row }) => (
          <Input
            aria-label={`Edit title for ${row.original.file_name}`}
            className="h-8 min-w-[180px]"
            onChange={(event) =>
              updateRow(row.original.id, (next) => ({
                ...next,
                title: event.target.value,
              }))
            }
            onClick={(event) => event.stopPropagation()}
            value={row.original.title}
          />
        ),
      },
      {
        accessorKey: 'tags',
        header: 'Tags',
        cell: ({ row }) => (
          <Input
            aria-label={`Edit tags for ${row.original.file_name}`}
            className="h-8 min-w-[180px]"
            onChange={(event) =>
              updateRow(row.original.id, (next) => ({
                ...next,
                tags: event.target.value
                  .split(',')
                  .map((item) => item.trim())
                  .filter(Boolean),
              }))
            }
            onClick={(event) => event.stopPropagation()}
            value={row.original.tags.join(', ')}
          />
        ),
      },
      {
        accessorKey: 'status',
        header: ({ column }) => (
          <DataTableSortableHeader label="Status" onToggle={() => column.toggleSorting(column.getIsSorted() === 'asc')} sorted={column.getIsSorted()} />
        ),
        cell: ({ row }) => (
          <Badge variant={row.original.status === 'error' ? 'destructive' : row.original.status === 'duplicate' ? 'warning' : 'secondary'}>
            {row.original.status}
          </Badge>
        ),
      },
      {
        accessorKey: 'error_code',
        header: 'Error Code',
        cell: ({ row }) => row.original.error_code || '-',
      },
      {
        accessorKey: 'target_suggestion',
        header: 'Suggested Target',
        cell: ({ row }) => (
          <Input
            aria-label={`Edit suggested target for ${row.original.file_name}`}
            className="h-8 min-w-[260px]"
            onChange={(event) =>
              updateRow(row.original.id, (next) => ({
                ...next,
                target_suggestion: event.target.value,
              }))
            }
            onClick={(event) => event.stopPropagation()}
            value={row.original.target_suggestion}
          />
        ),
      },
      {
        accessorKey: 'notes',
        header: 'Notes',
        cell: ({ row }) => (
          <Textarea
            aria-label={`Edit notes for ${row.original.file_name}`}
            className="min-h-[48px] min-w-[220px]"
            onChange={(event) =>
              updateRow(row.original.id, (next) => ({
                ...next,
                notes: event.target.value,
              }))
            }
            onClick={(event) => event.stopPropagation()}
            value={row.original.notes}
          />
        ),
      },
      {
        accessorKey: 'ignore',
        header: 'Ignore',
        cell: ({ row }) => (
          <Checkbox
            aria-label={`Toggle ignore for ${row.original.file_name}`}
            checked={row.original.ignore}
            onCheckedChange={(nextChecked) =>
              updateRow(row.original.id, (next) => ({
                ...next,
                ignore: nextChecked,
              }))
            }
            onClick={(event) => event.stopPropagation()}
          />
        ),
      },
      {
        accessorKey: 'confidence',
        header: ({ column }) => (
          <DataTableSortableHeader label="Confidence" onToggle={() => column.toggleSorting(column.getIsSorted() === 'asc')} sorted={column.getIsSorted()} />
        ),
        cell: ({ row }) => `${Math.round(row.original.confidence * 100)}%`,
      },
      {
        id: 'conflict_state',
        accessorFn: (row) => (conflictRowSet.has(row.id) || row.status === 'error' || row.status === 'duplicate' ? 'open' : 'none'),
        enableHiding: false,
        header: 'Conflict State',
        cell: () => null,
        filterFn: (row, columnId, value) => {
          const state = row.getValue(columnId) as string
          if (value === 'open') {
            return state === 'open'
          }
          if (value === 'error_only') {
            return row.original.status === 'error'
          }
          return true
        },
      },
      {
        id: 'actions',
        enableSorting: false,
        enableHiding: false,
        header: 'Actions',
        cell: ({ row }) => (
          <div className="text-right">
            <DataTableRowActions
              items={[
                {
                  key: 'preview',
                  label: 'Preview',
                  onSelect: () => setPreviewRowId(row.original.id),
                },
                {
                  key: 'toggle-ignore',
                  label: row.original.ignore ? 'Unignore' : 'Ignore',
                  onSelect: () =>
                    updateRow(row.original.id, (next) => ({
                      ...next,
                      ignore: !next.ignore,
                    })),
                },
              ]}
            />
          </div>
        ),
        meta: {
          headerClassName: 'text-right',
          cellClassName: 'text-right',
        },
      },
    ],
    [conflictRowSet, updateRow],
  )

  const table = useReactTable({
    data: effectiveRows,
    columns,
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      rowSelection,
      globalFilter: query,
    },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    onGlobalFilterChange: setQuery,
    getRowId: (row) => row.id,
    enableRowSelection: true,
    autoResetAll: false,
    globalFilterFn: (row, _columnId, filterValue) => {
      const keyword = String(filterValue ?? '').trim().toLowerCase()
      if (keyword.length === 0) {
        return true
      }
      const haystack = [
        row.original.file_name,
        row.original.title,
        row.original.category,
        row.original.error_code,
        row.original.target_suggestion,
      ]
        .join(' ')
        .toLowerCase()
      return haystack.includes(keyword)
    },
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  const selectedRows = table.getSelectedRowModel().rows.map((row) => row.original)

  const conflictsPrefetch = createRouteIntentPrefetchHandlers('conflicts')
  const applyPrefetch = createRouteIntentPrefetchHandlers('apply')

  const dirtyPatches = useMemo(() => {
    const patches: ManifestRowPatch[] = []
    for (const row of manifestRows) {
      const edited = editedMap[row.id]
      if (!edited) {
        continue
      }
      const patch = buildPatch(row, edited)
      if (patch) {
        patches.push(patch)
      }
    }
    return patches
  }, [editedMap, manifestRows])

  const previewRow = useMemo(() => effectiveRows.find((row) => row.id === previewRowId) ?? null, [effectiveRows, previewRowId])
  const previewEditedRow = previewRow ? editedMap[previewRow.id] ?? null : null

  const applyBatchCategory = () => {
    if (batchCategory.trim().length === 0 || selectedRows.length === 0) {
      return
    }
    for (const row of selectedRows) {
      updateRow(row.id, (next) => ({ ...next, category: batchCategory.trim() }))
    }
    toast.success(`Set category for selected rows: ${batchCategory}`)
  }

  const applyBatchIgnore = (value: boolean) => {
    if (selectedRows.length === 0) {
      return
    }
    for (const row of selectedRows) {
      updateRow(row.id, (next) => ({ ...next, ignore: value }))
    }
    toast.success(`${value ? 'Ignored' : 'Unignored'} ${selectedRows.length} selected rows.`)
  }

  const applyTemplate = () => {
    if (selectedRows.length === 0 || selectedTemplateId.length === 0) {
      return
    }
    const template = templates.find((item) => item.id === selectedTemplateId)
    if (!template) {
      return
    }
    for (const row of selectedRows) {
      updateRow(row.id, (next) => ({
        ...next,
        target_suggestion: applyTemplatePattern(template, next),
      }))
    }
    toast.success(`Applied template "${template.name}" to ${selectedRows.length} rows.`)
  }

  const saveEdits = async () => {
    if (dirtyPatches.length === 0) {
      toast.message('No pending edits to save.')
      return
    }
    const nextRows = await patchManifestRows(jobId, dirtyPatches)
    setManifestRows(nextRows)
    setEditedMap({})
    setRowSelection({})
    const nextConflicts = await getManifestConflicts(jobId)
    setConflicts(nextConflicts)
    toast.success(`Saved ${dirtyPatches.length} edits.`)
  }

  const saveView = async () => {
    if (viewName.trim().length === 0) {
      toast.warning('Enter a view name first.')
      return
    }
    try {
      const created = await createSavedView({
        name: viewName.trim(),
        scope: 'manifest',
        query: {
          query,
          statusFilter,
          conflictFilter,
          selectedTemplateId,
        },
      })
      setSavedViews((prev) => [created, ...prev])
      setViewName('')
      toast.success('View saved.')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save the view.')
    }
  }

  const applyView = (view: SavedView) => {
    setQuery(view.query.query ?? '')
    setStatusFilter(view.query.statusFilter ?? 'all')
    setConflictFilter((view.query.conflictFilter as 'all' | 'open' | 'error_only') ?? 'all')
    setSelectedTemplateId(view.query.selectedTemplateId ?? selectedTemplateId)
    toast.success(`Applied view: ${view.name}`)
  }

  const removeView = async (id: string) => {
    try {
      await deleteSavedView(id)
      setSavedViews((prev) => prev.filter((item) => item.id !== id))
      toast.success('View deleted.')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to delete the view.')
    }
  }

  const addTemplate = async () => {
    if (newTemplateName.trim().length === 0 || newTemplatePattern.trim().length === 0) {
      toast.warning('Template name and expression are required.')
      return
    }
    try {
      const created = await createNamingTemplate({
        name: newTemplateName.trim(),
        pattern: newTemplatePattern.trim(),
        description: 'Created in WebUI',
      })
      setTemplates((prev) => [created, ...prev])
      setSelectedTemplateId(created.id)
      setNewTemplateName('')
      toast.success('Naming template created.')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to create the naming template.')
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('manifest.title')}</CardTitle>
          <CardDescription>
            Job: {job?.id || jobId || 'unknown'}. Editable workflow for category, title, tags, notes, suggested target, and ignore state.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <Input className="md:col-span-2" onChange={(event) => setQuery(event.target.value)} placeholder="Search filename / category / error code / suggested target" value={query} />
            <Select aria-label="Filter manifest rows by status" onValueChange={setStatusFilter} value={statusFilter}>
              <option value="all">All statuses</option>
              <option value="pending">pending</option>
              <option value="error">error</option>
              <option value="duplicate">duplicate</option>
              <option value="applied">applied</option>
            </Select>
            <Select aria-label="Filter manifest rows by conflict state" onValueChange={(value) => setConflictFilter(value as 'all' | 'open' | 'error_only')} value={conflictFilter}>
              <option value="all">All conflict states</option>
              <option value="open">Open conflicts only</option>
              <option value="error_only">Errors only</option>
            </Select>
          </div>

          <DataTableToolbar
            leading={
              <>
                <div className="flex items-center gap-2">
                  <Input onChange={(event) => setBatchCategory(event.target.value)} placeholder="Set category for selected rows" value={batchCategory} />
                  <Button onClick={applyBatchCategory} size="sm" variant="outline">
                    Apply
                  </Button>
                </div>
                <Button onClick={() => applyBatchIgnore(true)} size="sm" variant="secondary">
                  Ignore Selected
                </Button>
                <Button onClick={() => applyBatchIgnore(false)} size="sm" variant="outline">
                  Unignore Selected
                </Button>
                <div className="flex items-center gap-2">
                  <Select aria-label="Select a naming template" onValueChange={setSelectedTemplateId} value={selectedTemplateId}>
                    {templates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name}
                      </option>
                    ))}
                  </Select>
                  <Button onClick={applyTemplate} size="sm" variant="outline">
                    Apply Template
                  </Button>
                </div>
                <Button onClick={() => void saveEdits()} size="sm">
                  Save Edits ({dirtyPatches.length})
                </Button>
              </>
            }
            onClearSelection={() => table.resetRowSelection()}
            selectionCount={selectedRows.length}
            totalCount={table.getFilteredRowModel().rows.length}
            trailing={<DataTableViewOptions label="Columns" table={table} />}
          />

          <div className="grid gap-3 rounded-xl border border-border p-3 lg:grid-cols-2">
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">Saved Views</p>
              <div className="flex gap-2">
                <Input onChange={(event) => setViewName(event.target.value)} placeholder="View name" value={viewName} />
                <Button onClick={() => void saveView()} size="sm" variant="outline">
                  Save View
                </Button>
              </div>
              <div className="flex flex-wrap gap-2">
                {savedViews.map((view) => (
                  <div className="flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-xs" key={view.id}>
                    <Button onClick={() => applyView(view)} size="sm" type="button" variant="ghost">
                      {view.name}
                    </Button>
                    <Button className="text-muted-foreground" onClick={() => void removeView(view.id)} size="sm" type="button" variant="ghost">
                      ×
                    </Button>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">Naming Templates</p>
              <Input onChange={(event) => setNewTemplateName(event.target.value)} placeholder="Template name" value={newTemplateName} />
              <Input
                onChange={(event) => setNewTemplatePattern(event.target.value)}
                placeholder="{category}/{title}__{hash8}"
                value={newTemplatePattern}
              />
              <Button onClick={() => void addTemplate()} size="sm" variant="outline">
                Create Template
              </Button>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">Open conflicts {conflicts.filter((item) => item.status === 'open').length}</Badge>
            <Button asChild size="sm" variant="outline">
              <Link {...conflictsPrefetch} to={`/conflicts/${jobId}`}>
                Open Full-Screen Conflict Center
              </Link>
            </Button>
            <Button asChild size="sm">
              <Link {...applyPrefetch} to={`/apply/${jobId}`}>
                Open Apply Dry-Run
              </Link>
            </Button>
          </div>

          <DataTableShell emptyDescription="Adjust the filters or run Analyze first." emptyTitle="No manifest rows to display" table={table} />

          <Alert className="border-warning/30 bg-warning/10">
            <AlertTitle>Editing Rules</AlertTitle>
            <AlertDescription>
              This workbench edits manifest fields only. It does not change the file system directly. Save edits before entering Apply dry-run.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      <RuleStudioSheet
        jobId={jobId}
        onApplied={() => {
          void refreshAll()
        }}
      />

      <Suspense fallback={<FeatureCardFallback title="Conflict Center Loading..." />}>
        <ConflictCenter
          conflicts={conflicts}
          jobId={jobId}
          onRefresh={() => {
            void refreshAll()
          }}
        />
      </Suspense>

      <Suspense fallback={<PreviewDrawerFallback />}>
        {previewRow ? (
          <PreviewDrawer
            editedRow={previewEditedRow}
            jobId={jobId}
            onOpenChange={(open) => {
              if (!open) {
                setPreviewRowId('')
              }
            }}
            open={Boolean(previewRow)}
            row={previewRow}
          />
        ) : null}
      </Suspense>
    </div>
  )
}
