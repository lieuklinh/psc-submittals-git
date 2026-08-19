export interface Project {
  id: string
  title: string
  pinned: boolean | number
  delete_requested_by: string | null
  role?: string
  my_role?: string
  uploaded_by?: string
  workflow_status?: string
  output_zip_path?: string | null
  qna_doc_id?: string | null
}

export interface SpecSection {
  id: string
  project_id: string
  section_number: string
  section_name: string | null
  section_text_reference: string | null
  section_summary: string | null
  order_index: number
  assigned_user_email: string | null
  status: 'active' | 'not_required' | 'archived'
  not_required_reason: string | null
}

export interface SubmittalItem {
  id: string
  project_id: string
  specification_section_id: string
  suffix: string
  display_number: string
  title: string
  submittal_type: string | null
  organization_id: string | null
  responsible_user_email: string | null
  status: string
  status_reason: string | null
  due_date: string | null
  notes: string | null
  is_archived: number | boolean
  revision_letter: string
}

export interface Organization {
  id: string
  organization_name: string
  organization_type: string
  primary_contact_name: string | null
  trade: string | null
  is_active: number | boolean
}

export interface ProjectMember {
  project_id: string
  user_email: string
  role: string
  status: string
  display_name: string | null
  company_role: string | null
  assigned_count: number
  last_activity_at: string | null
}

export interface DirectoryPerson {
  id: string
  email: string
  name: string
  job_title: string | null
  department: string | null
  office: string | null
  phone: string | null
}

export interface Notification {
  id: string
  user_email: string
  project_id: string
  message: string
  created_at: string
  is_read: number | boolean
}

export interface ActivityEntry {
  id: string
  project_id: string
  submittal_item_id: string | null
  actor_email: string
  action_type: string
  old_value: string | null
  new_value: string | null
  created_at: string
}

export interface Attachment {
  id: string
  submittal_item_id: string
  original_filename: string
  uploaded_by: string
  uploaded_at: string
  folder: string
  description: string | null
  vendor_version: string | null
  formal_revision: string | null
}

export interface Comment {
  id: string
  submittal_item_id: string
  author_email: string
  body: string
  created_at: string
}

export interface SectionFlag {
  id: string
  section_id: string
  project_id: string
  original_code: string
  embedded_code: string
  description: string
  llm_explanation: string
  suggested_code: string | null
  status: string
}

export interface WorkspaceResponse {
  role: string | null
  is_admin: boolean
  membership_status: string | null
  sections: SpecSection[]
  items: SubmittalItem[]
  organizations: Organization[]
  members: ProjectMember[]
}

// The approved standard submittal folder structure (2026-08 spec, section
// 10) — every attachment belongs to exactly one of these four.
export const ATTACHMENT_FOLDERS: [string, string][] = [
  ['from_vendor', '1. From Vendor'],
  ['to_engineer', '2. To Engineer'],
  ['from_engineer', '3. From Engineer'],
  ['final_approved', '4. Final Approved'],
]

export const SUBMITTAL_TYPES: [string, string][] = [
  ['product_data', 'Product Data'],
  ['shop_drawings', 'Shop Drawings'],
  ['samples', 'Samples'],
  ['material_sample', 'Material Sample'],
  ['mix_design', 'Mix Design'],
  ['test_report', 'Test Report'],
  ['certification', 'Certificate or Certification'],
  ['manufacturer_data', 'Manufacturer Data'],
  ['om_data', 'Operation and Maintenance Data'],
  ['closeout', 'Closeout Submittal'],
  ['mockup', 'Mockup'],
  ['design_calculations', 'Design Calculations'],
  ['coordination_drawings', 'Coordination Drawings'],
  ['warranty', 'Warranty'],
  ['informational', 'Informational Submittal'],
  ['other', 'Other'],
]

export const SUBMITTAL_STATUSES = [
  'unassigned', 'required', 'assigned', 'requested', 'received',
  'under_review', 'approved', 'approved_as_noted', 'revise_and_resubmit',
  'rejected', 'already_available', 'not_required', 'closed',
]


export const STATUS_LABELS: Record<string, string> = {
  unassigned: 'Unassigned', required: 'Required', assigned: 'Assigned',
  requested: 'Requested', received: 'Received', under_review: 'Under Review',
  approved: 'Approved', approved_as_noted: 'Approved as Noted',
  revise_and_resubmit: 'Revise and Resubmit', rejected: 'Rejected',
  already_available: 'Already Available', not_required: 'Not Required', closed: 'Closed',
}

export const ORGANIZATION_TYPES = ['subcontractor', 'vendor', 'supplier', 'manufacturer', 'consultant']

export const PROJECT_ROLES = ['owner_admin', 'admin', 'assignee', 'viewer']

export const ROLE_LABELS: Record<string, string> = {
  owner_admin: 'Owner Admin', admin: 'Admin', assignee: 'Assignee', viewer: 'Viewer',
}
