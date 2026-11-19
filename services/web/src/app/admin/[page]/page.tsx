import { EmptyState } from "@/components/EmptyState";
import { NAV_ITEMS_META } from "@/lib/nav";

/** 本期未实现页面占位（P4/P5/P7/P8/P9/P11 等，本期仅 5 页，见 Spec §5）。 */
export default async function PlaceholderPage({ params }: { params: Promise<{ page: string }> }) {
  const { page } = await params;
  const label = NAV_ITEMS_META[page] ?? page;
  return (
    <section>
      <div className="page-h"><b>{label}</b></div>
      <div className="card">
        <EmptyState title="本期未实现" sub={`「${label}」不在本期交付范围（Spec §5：#advice/#macro/#overview/#monitor/#datamgmt 五页）`} />
      </div>
    </section>
  );
}
