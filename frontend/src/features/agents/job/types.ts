export type Requirement = {
    id: string;
    text: string;
    priority: 'required' | 'preferred' | 'unspecified';
    category: 'skill' | 'experience' | 'education' | 'other';
    quote: string;
    source_start: number;
    source_end: number;
    source_line: number;
};
export type JobTask = {
    id: string;
    title: string;
    source_text: string;
    provider: 'rules' | 'deepseek';
    status: 'running' | 'completed' | 'needs_input' | 'failed';
    created_at: number;
    requirements: Requirement[];
    trace: {
        name: string;
        status: 'completed' | 'failed' | 'skipped';
        detail: string;
    }[];
    result: {
        summary: string;
    } | null;
    usage: {
        attempts: number;
        prompt_tokens: number;
        completion_tokens: number;
    };
    error: {
        code: string;
        message: string;
    } | null;
};
export type JobSummary = Pick<JobTask, 'id' | 'title' | 'provider' | 'status' | 'created_at'>;
export type Capabilities = {
    provider: 'rules' | 'deepseek';
    configured: boolean;
    max_source_length: number;
};
