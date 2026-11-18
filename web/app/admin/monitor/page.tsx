import { AdminShell } from "../components/AdminShell";
import { PageBody } from "../components/PageBody";

/** 运维监控（`#monitor` · AD-02） */
export default function Page() {
  return (
    <AdminShell active="monitor">
      <section id="monitor">
        <PageBody pageId="monitor" />
      </section>
    </AdminShell>
  );
}
