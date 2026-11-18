import { AdminShell } from "../components/AdminShell";
import { PageBody } from "../components/PageBody";

/** 策略与因子（`#strategy` · AD-05、FA-07/08） */
export default function Page() {
  return (
    <AdminShell active="strategy">
      <section id="strategy">
        <PageBody pageId="strategy" />
      </section>
    </AdminShell>
  );
}
