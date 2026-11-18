import { AdminShell } from "../components/AdminShell";
import { PageBody } from "../components/PageBody";

/** 数据管理（`#datamgmt` · AD-02、DL-05/06） */
export default function Page() {
  return (
    <AdminShell active="datamgmt">
      <section id="datamgmt">
        <PageBody pageId="datamgmt" />
      </section>
    </AdminShell>
  );
}
