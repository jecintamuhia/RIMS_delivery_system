import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Layers,
  Play,
  Plus,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { pricingVersionsApi, type ApiError } from "@/services/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { QueryError } from "@/components/layout/QueryError";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/features/auth/AuthProvider";
import { formatDate, formatDateTime } from "@/utils/format";
import type {
  PricingImportReport,
  PricingVersion,
  VersionValidationResult,
} from "@/types";

const today = () => new Date().toISOString().slice(0, 10);

interface VersionForm {
  label: string;
  effectiveFrom: string;
  effectiveTo?: string | null;
  currency: string;
  notes?: string;
}

export default function PricingVersionsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { canEdit } = useAuth();
  const [newDrawer, setNewDrawer] = useState(false);
  const [importDrawer, setImportDrawer] = useState(false);
  const [validatingVersion, setValidatingVersion] =
    useState<PricingVersion | null>(null);
  const [validationResult, setValidationResult] =
    useState<VersionValidationResult | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [csvFilename, setCsvFilename] = useState("");
  const [csvLabel, setCsvLabel] = useState("RIMs Transport Cost List");
  const [csvEffectiveFrom, setCsvEffectiveFrom] = useState(today());
  const [importReport, setImportReport] = useState<PricingImportReport | null>(null);

  const { data: versions, isLoading, error, refetch } = useQuery({
    queryKey: ["pricing-versions"],
    queryFn: pricingVersionsApi.list,
  });
  const { data: importFiles = [], isLoading: filesLoading } = useQuery({
    queryKey: ["pricing-import-files"],
    queryFn: pricingVersionsApi.files,
    enabled: importDrawer,
  });

  const versionForm = useForm<VersionForm>({
    defaultValues: {
      label: "",
      effectiveFrom: today(),
      effectiveTo: null,
      currency: "KES",
      notes: "",
    },
  });

  const createMutation = useMutation({
    mutationFn: (v: VersionForm) =>
      pricingVersionsApi.create({
        label: v.label,
        effectiveFrom: v.effectiveFrom,
        effectiveTo: v.effectiveTo || null,
        currency: v.currency,
        notes: v.notes || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pricing-versions"] });
      setNewDrawer(false);
      versionForm.reset();
      toast.success("Draft pricing version created");
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Failed to create version"),
  });

  const validateMutation = useMutation({
    mutationFn: (id: string) => pricingVersionsApi.validate(id),
    onSuccess: (result) => {
      setValidationResult(result);
      toast.success(
        result.valid
          ? "Validation passed - ready for activation"
          : "Validation found issues blocking activation",
      );
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Validation request failed"),
  });

  const approveMutation = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      pricingVersionsApi.confirmValidation(id, note || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pricing-versions"] });
      toast.success("Pricing version approved for activation");
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Failed to record approval"),
  });

  const activateMutation = useMutation({
    mutationFn: (id: string) => pricingVersionsApi.activate(id),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["pricing-versions"] });
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setValidatingVersion(null);
      setValidationResult(null);
      toast.success(`Version '${res.label}' is now ACTIVE`);
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Failed to activate version"),
  });

  const retireMutation = useMutation({
    mutationFn: (id: string) => pricingVersionsApi.retire(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pricing-versions"] });
      toast.success("Pricing version retired");
    },
    onError: (e) =>
      toast.error((e as ApiError).message || "Failed to retire version"),
  });

  const importMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      pricingVersionsApi.importCsv({
        filename: csvFilename,
        label: csvLabel,
        effectiveFrom: csvEffectiveFrom,
        dryRun,
      }),
    onSuccess: (report) => {
      setImportReport(report);
      if (report.dryRun) {
        toast.success(
          report.problems.length
            ? `Review ${report.problems.length} import issue(s)`
            : `Preview ready: ${report.destinationCount} destinations and ${report.ruleCount} rules`,
        );
        return;
      }
      qc.invalidateQueries({ queryKey: ["pricing-versions"] });
      qc.invalidateQueries({ queryKey: ["destinations"] });
      qc.invalidateQueries({ queryKey: ["pricing-rules"] });
      setImportDrawer(false);
      setImportReport(null);
      toast.success(`Imported ${report.ruleCount} prices into '${report.label}'`);
    },
    onError: (e) => toast.error((e as ApiError).message || "CSV import failed"),
  });

  const startValidation = (ver: PricingVersion) => {
    setValidatingVersion(ver);
    setValidationResult(null);
    setReviewNote(ver.validationNote ?? "");
    validateMutation.mutate(ver.id);
  };

  const activeVersion = versions?.find((v) => v.status === "active");

  return (
    <>
      <PageHeader
        title="Pricing Versions"
        description="Manage RIMs delivery price lists. Price lists follow a strict DRAFT → REVIEW → ACTIVE lifecycle to ensure historical quotes remain reproducible."
        actions={
          canEdit && (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setImportReport(null);
                  setImportDrawer(true);
                }}
              >
                <Upload className="h-4 w-4" aria-hidden />
                Import CSV
              </Button>
              <Button size="sm" onClick={() => setNewDrawer(true)}>
                <Plus className="h-4 w-4" aria-hidden />
                New Version
              </Button>
            </div>
          )
        }
      />

      {error ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-28 w-full rounded-lg" />
          <Skeleton className="h-72 w-full rounded-lg" />
        </div>
      ) : (
        <div className="space-y-6">
          {/* Active Version Highlight */}
          {activeVersion ? (
            <div className="flex flex-col gap-4 rounded-lg border border-brand/40 bg-brand-soft/40 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2.5 py-0.5 text-small font-medium text-brand-strong">
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
                    Current Active Price List
                  </span>
                  <span className="text-small text-muted">
                    Effective from {formatDate(activeVersion.effectiveFrom)}
                  </span>
                </div>
                <h2 className="text-h2 font-semibold text-ink">
                  {activeVersion.label}
                </h2>
                <p className="text-small text-muted">
                  {activeVersion.ruleCount} destinations priced ·{" "}
                  {activeVersion.destinationCount} delivery areas configured ·{" "}
                  Currency: {activeVersion.currency}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Link to="/admin/pricing-rules">
                  <Button variant="secondary" size="sm">
                    View Rules
                    <ArrowRight className="h-4 w-4" aria-hidden />
                  </Button>
                </Link>
                {canEdit && (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={retireMutation.isPending}
                    onClick={() => retireMutation.mutate(activeVersion.id)}
                  >
                    Retire
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-start gap-3 rounded-lg border border-warn/40 bg-warn-soft/40 p-5">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warn" aria-hidden />
              <div className="space-y-1">
                <p className="font-semibold text-ink">No Active Pricing Version</p>
                <p className="text-small text-muted">
                  Customer quotes cannot be calculated automatically until a
                  pricing version is activated. Review and activate a draft
                  version below.
                </p>
              </div>
            </div>
          )}

          {/* Versions Table */}
          <div className="overflow-hidden rounded-lg border border-line bg-surface shadow-sm">
            <div className="border-b border-line px-5 py-4">
              <h3 className="text-h2 font-medium">All Pricing Versions</h3>
              <p className="text-small text-muted">
                Only one version can be active at a time. Activating a version
                automatically retires the previous one.
              </p>
            </div>
            {!versions?.length ? (
              <div className="p-8 text-center text-muted">
                <Layers className="mx-auto h-8 w-8 text-muted/60" aria-hidden />
                <p className="mt-2 font-medium">No pricing versions configured</p>
                <p className="text-small">
                  Import RIMs price list CSV or create a new draft version.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-small">
                  <thead className="border-b border-line bg-canvas/40 text-muted">
                    <tr>
                      <th className="px-5 py-3 font-medium">Version</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Effective</th>
                      <th className="px-4 py-3 font-medium text-right">Rules</th>
                      <th className="px-4 py-3 font-medium">Validation Status</th>
                      <th className="px-5 py-3 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {versions.map((ver) => (
                      <tr key={ver.id} className="hover:bg-canvas/30">
                        <td className="px-5 py-4">
                          <p className="font-medium text-ink">{ver.label}</p>
                          <p className="text-small text-muted">
                            Created {formatDateTime(ver.createdAt)}
                          </p>
                        </td>
                        <td className="px-4 py-4">
                          <StatusBadge
                            tone={
                              ver.status === "active"
                                ? "ok"
                                : ver.status === "draft"
                                  ? "warn"
                                  : "neutral"
                            }
                          >
                            {ver.status.toUpperCase()}
                          </StatusBadge>
                        </td>
                        <td className="px-4 py-4 tabular-nums text-muted">
                          {formatDate(ver.effectiveFrom)}
                          {ver.effectiveTo ? ` – ${formatDate(ver.effectiveTo)}` : ""}
                        </td>
                        <td className="px-4 py-4 text-right tabular-nums font-medium text-ink">
                          {ver.ruleCount}
                        </td>
                        <td className="px-4 py-4">
                          {ver.validatedAt ? (
                            <div className="space-y-0.5">
                              <span className="inline-flex items-center gap-1 text-small font-medium text-brand-strong">
                                <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
                                Approved
                              </span>
                              <p className="text-[11px] text-muted truncate max-w-48">
                                {ver.validationNote || "Validation confirmed"}
                              </p>
                            </div>
                          ) : (
                            <span className="text-small text-muted">
                              Unreviewed
                            </span>
                          )}
                        </td>
                        <td className="px-5 py-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            {ver.status === "draft" && canEdit && (
                              <>
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  onClick={() => startValidation(ver)}
                                >
                                  Review & Activate
                                </Button>
                              </>
                            )}
                            {ver.status === "active" && canEdit && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => retireMutation.mutate(ver.id)}
                              >
                                Retire
                              </Button>
                            )}
                            {ver.status === "retired" && (
                              <span className="text-small text-muted">
                                Archived
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Validation / Activation Drawer */}
      <Drawer
        open={!!validatingVersion}
        onClose={() => {
          setValidatingVersion(null);
          setValidationResult(null);
        }}
        title={`Review & Activate: ${validatingVersion?.label}`}
        footer={
          <div className="flex items-center justify-between w-full">
            <Button
              variant="secondary"
              onClick={() => {
                setValidatingVersion(null);
                setValidationResult(null);
              }}
            >
              Close
            </Button>
            {validatingVersion && validationResult && (
              <div className="flex items-center gap-2">
                {!validatingVersion.validatedAt && (
                  <Button
                    variant="secondary"
                    loading={approveMutation.isPending}
                    onClick={() =>
                      approveMutation.mutate({
                        id: validatingVersion.id,
                        note: reviewNote,
                      })
                    }
                  >
                    Confirm Review
                  </Button>
                )}
                <Button
                  loading={activateMutation.isPending}
                  disabled={!validationResult.valid}
                  onClick={() => activateMutation.mutate(validatingVersion.id)}
                >
                  <Play className="h-4 w-4" aria-hidden />
                  Activate Price List
                </Button>
              </div>
            )}
          </div>
        }
      >
        <div className="space-y-6">
          {validateMutation.isPending ? (
            <div className="space-y-3 py-6">
              <Skeleton className="h-10" />
              <Skeleton className="h-24" />
            </div>
          ) : validationResult ? (
            <div className="space-y-5">
              {/* Verdict Banner */}
              <div
                className={`rounded-lg border p-4 ${
                  validationResult.valid
                    ? "border-brand/40 bg-brand-soft/40"
                    : "border-danger/40 bg-danger-soft/40"
                }`}
              >
                <div className="flex items-start gap-3">
                  {validationResult.valid ? (
                    <CheckCircle2
                      className="mt-0.5 h-5 w-5 shrink-0 text-brand"
                      aria-hidden
                    />
                  ) : (
                    <AlertCircle
                      className="mt-0.5 h-5 w-5 shrink-0 text-danger"
                      aria-hidden
                    />
                  )}
                  <div>
                    <h4 className="font-semibold text-ink">
                      {validationResult.valid
                        ? "Validation Passed"
                        : "Activation Blocked"}
                    </h4>
                    <p className="mt-1 text-small text-muted">
                      {validationResult.summary}
                    </p>
                  </div>
                </div>
              </div>

              {/* Reviewer Note */}
              <div className="space-y-2">
                <label className="text-small font-medium text-ink">
                  Reviewer note (audit record)
                </label>
                <Input
                  label="Reviewer note"
                  placeholder="e.g. Verified against RIMs transport cost sheet"
                  value={reviewNote}
                  onChange={(e) => setReviewNote(e.target.value)}
                />
              </div>

              {/* Findings */}
              <div className="space-y-3">
                <h4 className="text-small font-semibold uppercase tracking-wider text-muted">
                  Findings ({validationResult.findings.length})
                </h4>
                {!validationResult.findings.length ? (
                  <p className="text-small text-muted">
                    Zero errors or warnings detected in this price list.
                  </p>
                ) : (
                  <ul className="space-y-2 max-h-72 overflow-y-auto">
                    {validationResult.findings.map((f, i) => (
                      <li
                        key={i}
                        className={`rounded border p-3 text-small ${
                          f.severity === "error"
                            ? "border-danger/30 bg-danger-soft/30 text-danger"
                            : "border-warn/30 bg-warn-soft/30 text-ink"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-semibold">
                            {f.destinationName
                              ? `${f.destinationName} (${f.code})`
                              : f.code}
                          </span>
                          <span
                            className={`rounded px-1.5 py-0.2 text-[10px] font-bold uppercase ${
                              f.severity === "error"
                                ? "bg-danger text-surface"
                                : "bg-warn text-surface"
                            }`}
                          >
                            {f.severity}
                          </span>
                        </div>
                        <p className="mt-1 text-muted">{f.message}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ) : null}
        </div>
      </Drawer>

      {/* New Draft Version Drawer */}
      <Drawer
        open={newDrawer}
        onClose={() => setNewDrawer(false)}
        title="Create Draft Pricing Version"
        footer={
          <div className="flex justify-end gap-3 w-full">
            <Button variant="secondary" onClick={() => setNewDrawer(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              form="version-form"
              loading={createMutation.isPending}
            >
              Create Version
            </Button>
          </div>
        }
      >
        <form
          id="version-form"
          className="space-y-4"
          onSubmit={versionForm.handleSubmit((v) => createMutation.mutate(v))}
        >
          <Input
            label="Version label"
            placeholder="e.g. RIMs Q4 2026 Price List"
            required
            {...versionForm.register("label", { required: true })}
          />
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Effective from"
              type="date"
              required
              {...versionForm.register("effectiveFrom", { required: true })}
            />
            <Input
              label="Effective to"
              type="date"
              optional
              {...versionForm.register("effectiveTo")}
            />
          </div>
          <Input
            label="Currency"
            disabled
            value="KES"
            {...versionForm.register("currency")}
          />
          <Input
            label="Notes"
            optional
            placeholder="Details or reference"
            {...versionForm.register("notes")}
          />
        </form>
      </Drawer>

      {/* Import CSV Drawer */}
      <Drawer
        open={importDrawer}
        onClose={() => setImportDrawer(false)}
        title="Import Price List CSV"
        footer={
          <div className="flex justify-end gap-3 w-full">
            <Button variant="secondary" onClick={() => setImportDrawer(false)}>
              Cancel
            </Button>
            {!importReport ? (
              <Button
                loading={importMutation.isPending}
                disabled={!csvFilename || !csvLabel.trim() || !csvEffectiveFrom}
                onClick={() => importMutation.mutate(true)}
              >
                Check price list
              </Button>
            ) : (
              <Button
                loading={importMutation.isPending}
                disabled={!!importReport.problems.length || !importReport.dryRun}
                onClick={() => importMutation.mutate(false)}
              >
                Create draft version
              </Button>
            )}
          </div>
        }
      >
        <div className="space-y-4">
          <p className="text-small text-muted">
            Select a price list installed on the RIMs API. The server checks it
            first; applying a clean preview creates a draft version only.
          </p>

          <Select
            label="Server price list"
            value={csvFilename}
            onChange={(e) => {
              setCsvFilename(e.target.value);
              setImportReport(null);
            }}
            options={importFiles.map((file) => ({ value: file, label: file }))}
            placeholder={filesLoading ? "Loading available lists…" : "Choose a CSV"}
            disabled={filesLoading || !importFiles.length}
            error={!filesLoading && !importFiles.length ? "No CSV files are installed on the API." : undefined}
          />

          <Input
            label="Version label"
            value={csvLabel}
            onChange={(e) => {
              setCsvLabel(e.target.value);
              setImportReport(null);
            }}
          />
          <Input
            label="Effective from"
            type="date"
            value={csvEffectiveFrom}
            onChange={(e) => {
              setCsvEffectiveFrom(e.target.value);
              setImportReport(null);
            }}
          />

          {importReport && (
            <section className="rounded-md border border-line bg-canvas/50 p-4" aria-live="polite">
              <h3 className="font-semibold">Import preview</h3>
              <p className="mt-1 text-small text-muted">
                {importReport.destinationCount} destinations · {importReport.ruleCount} rules
              </p>
              {importReport.problems.length > 0 ? (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-small text-danger">
                  {importReport.problems.map((problem, index) => <li key={`${index}-${problem}`}>{problem}</li>)}
                </ul>
              ) : (
                <p className="mt-3 text-small text-ok">No import issues found. Applying creates a draft; it does not activate prices.</p>
              )}
            </section>
          )}
        </div>
      </Drawer>
    </>
  );
}
