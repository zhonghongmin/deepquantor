declare module "pg" {
  export interface QueryResult {
    rows: any[]; // eslint-disable-line @typescript-eslint/no-explicit-any
    rowCount: number | null;
  }
  export interface PoolClient {
    query(sql: string, params?: unknown[]): Promise<QueryResult>;
    release(): void;
  }
  export class Pool {
    constructor(config?: {
      connectionString?: string;
      max?: number;
      connectionTimeoutMillis?: number;
    });
    query(sql: string, params?: unknown[]): Promise<QueryResult>;
    connect(): Promise<PoolClient>;
    end(): Promise<void>;
  }
}
