export type EvidenceType = 'self_claimed' | 'portfolio_supported' | 'task_verified';
export type DiagnosisItem = {
    requirement_id: string | null;
    claim_content: string;
    matched_requirement: string;
    evidence_type: EvidenceType | null;
    evidence_excerpt: string | null;
    confidence_score: number;
};
export type DiagnosisResult = {
    schema_version: number;
    summary: string;
    strengths: DiagnosisItem[];
    gaps: DiagnosisItem[];
    pending_verification: DiagnosisItem[];
};
export type DiagnosisStatus = 'running' | 'completed' | 'needs_input' | 'failed';
export type DiagnosisDetail = {
    id: string;
    resume_id: string;
    job_analysis_id: string;
    status: DiagnosisStatus;
    result: DiagnosisResult;
    created_at: number;
    updated_at: number;
};
export type DiagnosisSummary = {
    id: string;
    resume_id: string;
    job_analysis_id: string;
    status: DiagnosisStatus;
    resume_title: string;
    job_title: string;
    summary: string;
    created_at: number;
};
export type DiagnosisCapabilities = {
    provider: 'rules' | 'deepseek';
    configured: boolean;
    max_source_length: number;
};