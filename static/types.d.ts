// /api/* 的书面契约：前端 JSDoc 检查（tsc --noEmit）与将来 Agent 接入共用一份。
// 字段来源：engine.FigureSearcher.search() 的结果拼装 + server.py 的 job/presets 响应。

interface SearchItem {
    id: number;
    item_key: string;
    att_key: string;
    title: string;
    year: number;
    journal: string;
    journal_abbr: string;
    authors: string;
    fig_no: string;
    caption: string;
    context_text: string;
    image_path: string;
    thumb_name: string;
    page_no: number;
    origin: 'whole' | 'panel';
    panels_json: string;
    wikilink: string;
    link_kind: string;
    /** 语义相似度 + 关键词加分，可 > 1（页面展示只用 semantic_sim） */
    score: number;
    /** 纯余弦相似度，granite-97m 典型区间 0.55–0.98 */
    semantic_sim: number;
    rating: number;
}

type JobStage = 'queued' | 'scanning' | 'extracting' | 'done' | 'error';

interface JobState {
    id: string;
    kind?: string;
    stage: JobStage;
    total: number;
    done: number;
    current?: string;
    current_journal?: string;
    mode?: string;
    message?: string;
    new_figures?: number;
    started_at?: number;
    finished_at?: number;
    updated_at?: number;
}

interface Preset {
    label: string;
    query: string;
}

interface StatsPayload {
    total_figures: number;
    total_papers: number;
}

interface FacetsPayload {
    total_figures: number;
    total_papers: number;
    year_range: [number, number] | null;
    families: Record<string, number>;
    journals: [string, number][];
}
