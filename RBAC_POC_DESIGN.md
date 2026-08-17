# Role-Based Access Control (RBAC) - POC Design

**Fine-grained data visibility across multiple users with different roles.**

---

## Overview

Enable organizational data sharing with role-based access:
- **Admin**: See all organization data
- **Team Lead**: See own + team data
- **Team Member**: See own + team shared data
- **Guest**: See only explicitly shared files

---

## Database Schema (New Tables)

### 1. Users & Organization

```sql
-- User roles and organizational hierarchy
CREATE TABLE globus_users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    email VARCHAR(255) NOT NULL UNIQUE,
    organization_id INT NOT NULL,
    role_id INT NOT NULL,
    team_id INT,
    status ENUM('active', 'inactive', 'suspended') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES globus_organizations(id),
    FOREIGN KEY (role_id) REFERENCES globus_roles(id),
    FOREIGN KEY (team_id) REFERENCES globus_teams(id)
);

-- Roles in the system
CREATE TABLE globus_roles (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    level INT NOT NULL,  -- 1=guest, 2=member, 3=lead, 4=admin
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO globus_roles (name, description, level) VALUES
('guest', 'Limited access to shared files', 1),
('member', 'Own data + team shared data', 2),
('team_lead', 'Own + team data', 3),
('admin', 'All organization data', 4);

-- Organizations
CREATE TABLE globus_organizations (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Teams within organization
CREATE TABLE globus_teams (
    id INT PRIMARY KEY AUTO_INCREMENT,
    organization_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    manager_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES globus_organizations(id),
    FOREIGN KEY (manager_id) REFERENCES globus_users(id)
);
```

### 2. File Access Control

```sql
-- Which users/roles can access which files
CREATE TABLE globus_file_permissions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    file_id INT NOT NULL,
    owner_email VARCHAR(255) NOT NULL,
    accessible_by_role VARCHAR(50),  -- NULL=owner only, 'team'=team, 'org'=org, 'guest'=explicit
    accessible_to_email VARCHAR(255),  -- NULL=all with role, specific email=explicit
    access_level ENUM('view', 'comment', 'edit') DEFAULT 'view',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES globus_vault_files(id),
    INDEX (owner_email, accessible_by_role, accessible_to_email)
);

-- Grant table for explicit access
CREATE TABLE globus_file_grants (
    id INT PRIMARY KEY AUTO_INCREMENT,
    file_id INT NOT NULL,
    owner_email VARCHAR(255) NOT NULL,
    granted_to_email VARCHAR(255) NOT NULL,
    access_level ENUM('view', 'comment', 'edit') DEFAULT 'view',
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES globus_vault_files(id),
    INDEX (owner_email, granted_to_email),
    INDEX (granted_to_email)
);
```

### 3. Audit Trail

```sql
CREATE TABLE globus_rbac_audit (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_email VARCHAR(255) NOT NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),  -- 'file', 'folder', 'user'
    resource_id INT,
    resource_email VARCHAR(255),
    old_value TEXT,
    new_value TEXT,
    status VARCHAR(20),  -- 'allowed', 'denied'
    reason TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (user_email, timestamp),
    INDEX (resource_email, timestamp)
);
```

---

## Access Control Logic

### 1. Who Can Access What?

```python
# From new module: globus_rbac.py

def can_access_file(requesting_user_email, file_owner_email, file_id):
    """
    Check if requesting_user can access file owned by file_owner.
    
    Access hierarchy:
    1. Owner can always access own files
    2. Admin can access all org files
    3. Team lead can access own + team files
    4. Member can access own + team shared files
    5. Guest can access only explicitly granted files
    """
    
    # 1. Owner always has access
    if requesting_user_email == file_owner_email:
        return True, "owner"
    
    # 2. Get requester's role
    requester = get_user_info(requesting_user_email)
    if not requester:
        return False, "user_not_found"
    
    # 3. Admin can see everything
    if requester['role'] == 'admin':
        log_access("access_granted_admin", requesting_user_email, file_id, file_owner_email)
        return True, "admin"
    
    # 4. Check if same organization
    file_owner = get_user_info(file_owner_email)
    if requester['organization_id'] != file_owner['organization_id']:
        log_access("access_denied_org", requesting_user_email, file_id, file_owner_email)
        return False, "different_organization"
    
    # 5. Check if same team
    if requester['role'] == 'team_lead':
        if requester['team_id'] == file_owner['team_id']:
            log_access("access_granted_team_lead", requesting_user_email, file_id, file_owner_email)
            return True, "team_lead"
    
    if requester['role'] == 'member':
        if requester['team_id'] == file_owner['team_id']:
            # Check if file is marked as team-shared
            is_shared = db_read(
                "SELECT 1 FROM globus_file_permissions 
                 WHERE file_id=%s AND accessible_by_role='team'",
                (file_id,))
            if is_shared:
                log_access("access_granted_team_member", requesting_user_email, file_id, file_owner_email)
                return True, "team_member"
    
    # 6. Check explicit grants
    grant = db_read(
        "SELECT access_level FROM globus_file_grants 
         WHERE file_id=%s AND granted_to_email=%s",
        (file_id, requesting_user_email))
    
    if grant:
        log_access("access_granted_explicit", requesting_user_email, file_id, file_owner_email)
        return True, f"granted:{grant[0]['access_level']}"
    
    log_access("access_denied", requesting_user_email, file_id, file_owner_email)
    return False, "no_permission"
```

### 2. Modified Search Function with RBAC

```python
def globus_search_files_with_rbac(requesting_user_email, query, limit=5):
    """
    Search files but only return files the user can access.
    
    This replaces the original globus_search_files.
    """
    requester = get_user_info(requesting_user_email)
    
    if requester['role'] == 'admin':
        # Admin: search all org files
        files = db_read(
            "SELECT * FROM globus_vault_files 
             WHERE organization_id=%s AND filename LIKE %s
             ORDER BY modified_at DESC LIMIT %s",
            (requester['organization_id'], f"%{query}%", limit))
        
    elif requester['role'] == 'team_lead':
        # Team lead: own + team files
        files = db_read(
            "SELECT * FROM globus_vault_files 
             WHERE organization_id=%s 
             AND (email=%s OR team_id=%s)
             AND filename LIKE %s
             ORDER BY modified_at DESC LIMIT %s",
            (requester['organization_id'], requesting_user_email, 
             requester['team_id'], f"%{query}%", limit))
        
    elif requester['role'] == 'member':
        # Member: own + team shared files + explicit grants
        files = db_read(
            """
            SELECT DISTINCT f.* FROM globus_vault_files f
            WHERE f.organization_id=%s AND f.filename LIKE %s
            AND (
                f.email=%s  -- Own files
                OR (f.team_id=%s AND f.id IN (
                    SELECT file_id FROM globus_file_permissions 
                    WHERE accessible_by_role='team'
                ))
                OR f.id IN (
                    SELECT file_id FROM globus_file_grants 
                    WHERE granted_to_email=%s
                )
            )
            ORDER BY f.modified_at DESC LIMIT %s
            """,
            (requester['organization_id'], f"%{query}%",
             requesting_user_email, requester['team_id'],
             requesting_user_email, limit))
        
    else:  # guest
        # Guest: only explicitly granted files
        files = db_read(
            """
            SELECT DISTINCT f.* FROM globus_vault_files f
            WHERE f.id IN (
                SELECT file_id FROM globus_file_grants 
                WHERE granted_to_email=%s
            )
            AND f.filename LIKE %s
            ORDER BY f.modified_at DESC LIMIT %s
            """,
            (requesting_user_email, f"%{query}%", limit))
    
    return files or []
```

### 3. Drive Semantic Search with RBAC

```python
def globus_search_drive_semantic_with_rbac(requesting_user_email, query, limit=10, **filters):
    """
    Semantic search over Drive but only return accessible files.
    """
    requester = get_user_info(requesting_user_email)
    
    # 1. Get FAISS indexes user can access
    if requester['role'] == 'admin':
        # Admin can search all users' indexes in same org
        accessible_emails = db_read(
            "SELECT DISTINCT email FROM globus_vault_files 
             WHERE organization_id=%s AND source_type='google-drive'",
            (requester['organization_id'],))
        search_emails = [r['email'] for r in (accessible_emails or [])]
        
    elif requester['role'] == 'team_lead':
        # Team lead can search own + team members' indexes
        search_emails = [requesting_user_email]
        team_members = db_read(
            "SELECT email FROM globus_users 
             WHERE team_id=%s AND organization_id=%s",
            (requester['team_id'], requester['organization_id']))
        search_emails.extend([r['email'] for r in (team_members or [])])
        
    elif requester['role'] == 'member':
        # Member can only search own index
        search_emails = [requesting_user_email]
        
    else:  # guest
        # Guest cannot use semantic search
        return {"error": "insufficient_permissions"}
    
    # 2. Search all accessible indexes
    merged_results = []
    
    for email_to_search in search_emails:
        # Get this user's Google accounts
        accounts = db_read(
            "SELECT DISTINCT provider_account FROM globus_oauth_connections 
             WHERE email=%s AND source_types LIKE '%%drive%%'",
            (email_to_search,))
        
        for account_row in (accounts or []):
            account = account_row['provider_account']
            
            # Search FAISS
            results = search_drive_index(email_to_search, account, query, limit=limit, **filters)
            
            if isinstance(results, list):
                # Add owner info
                for r in results:
                    r['owner'] = email_to_search
                    r['accessible'] = can_access_file(requesting_user_email, email_to_search, r.get('file_id'))
                
                # Only include accessible files
                merged_results.extend([r for r in results if r['accessible'][0]])
    
    # 3. Sort by relevance and return top N
    merged_results.sort(key=lambda r: r.get('score', 0), reverse=True)
    return merged_results[:limit]
```

---

## Example Scenarios

### Scenario 1: Admin User

```
User: admin@company.com (Role: Admin)

Search: "Find all budget files"

Access:
✓ Own files
✓ All team members' files
✓ All organization files
✓ All FAISS indexes in organization

Results:
- alice@company.com/budget.xlsx
- bob@company.com/budget_Q3.pdf
- sales-team@company.com/budget_plan.xlsx
- ...all 10,014 organization files if matching
```

### Scenario 2: Team Lead

```
User: alice@company.com (Role: Team Lead, Team: Sales)
Team Members: bob@company.com, carol@company.com

Search: "Find budget files"

Access:
✓ Own files
✓ Team members' files (bob, carol)
✗ Other teams' files
✗ Admin-only files

Results:
- alice@company.com/my_budget.xlsx (owned)
- bob@company.com/budget_draft.xlsx (team member)
- carol@company.com/budget_notes.pdf (team member)
✗ finance-team files (different team)
```

### Scenario 3: Team Member

```
User: bob@company.com (Role: Member, Team: Sales)

Search: "Find budget files"

Access:
✓ Own files
✓ Team-shared files (marked as team-accessible)
✗ Other team members' private files
✗ Other teams' files

Results:
- bob@company.com/budget.xlsx (owned)
- sales_team_shared/budget_template.xlsx (team-shared)
✗ alice@company.com/my_budget.xlsx (not shared)
✗ finance_team/budget.pdf (different team)
```

### Scenario 4: Guest User

```
User: guest@external.com (Role: Guest)

Access:
✓ Only explicitly granted files
✗ Own files (no sync)
✗ Team files
✗ Organization files

Grant: admin@company.com shared "Q3_Report.pdf" with guest@external.com

Results:
- Q3_Report.pdf (explicitly granted)
✗ All other files
```

---

## Implementation Checklist

### Phase 1: Database Setup
- [ ] Create globus_users table
- [ ] Create globus_roles table (with 4 default roles)
- [ ] Create globus_organizations table
- [ ] Create globus_teams table
- [ ] Create globus_file_permissions table
- [ ] Create globus_file_grants table
- [ ] Create globus_rbac_audit table
- [ ] Add organization_id, team_id to globus_vault_files
- [ ] Migrate existing data (assign to default org/team)

### Phase 2: Core RBAC Functions
- [ ] Implement `can_access_file(user_email, owner_email, file_id)`
- [ ] Implement `get_user_info(email)`
- [ ] Implement `log_access(action, user_email, resource, status)`
- [ ] Implement permission checking helpers

### Phase 3: Search Integration
- [ ] Update `globus_search_files()` → `globus_search_files_with_rbac()`
- [ ] Update `globus_search_content()` → with RBAC
- [ ] Update `globus_search_drive_semantic()` → with RBAC
- [ ] Update `globus_read_file()` → with permission check

### Phase 4: Tool Dispatch
- [ ] Update orchestrator to pass user_email to all tools
- [ ] Add RBAC check before each tool execution
- [ ] Log all access attempts in audit table

### Phase 5: Admin Interface
- [ ] User management UI
- [ ] Role assignment
- [ ] Permission management
- [ ] Audit log viewer

---

## Key Features

### ✅ Fine-Grained Control
- Role-based (role determines access level)
- Team-based (same team can share)
- Explicit grants (granular per-file sharing)
- Access levels: view, comment, edit

### ✅ Audit Trail
- Every access logged
- Who accessed what, when, and from where
- Allowed vs denied attempts
- Export audit logs for compliance

### ✅ Hierarchical Access
```
Admin > Team Lead > Member > Guest

Admin:      Can access all org data
Team Lead:  Can access own + team data
Member:    Can access own + team-shared
Guest:     Can access only granted files
```

### ✅ Backward Compatible
- Existing single-user mode still works
- Multi-user mode is optional
- Can migrate gradually

---

## Security Considerations

### Minimum Required Checks

1. **At Query Level**
   ```python
   # Before returning any data
   if not can_access_file(requesting_user, file_owner, file_id):
       return {"error": "access_denied"}
   ```

2. **At Tool Level**
   ```python
   # In every tool dispatcher
   def execute_tool(requesting_user, tool_name, args):
       # Check permission first
       allowed, reason = check_permission(requesting_user, tool_name, args)
       if not allowed:
           log_access("denied", requesting_user, tool_name, reason)
           return {"error": "permission_denied"}
   ```

3. **At API Level**
   ```python
   # Verify session email matches request
   session_email = verify_session(request.cookies)
   if session_email != requesting_user:
       return {"error": "session_invalid"}
   ```

### Prevent Escalation
- Role assignment restricted to admins
- Organization changes require audit
- Team transfer requires approval
- Guest access is explicit, always

---

## Migration from Single-User to Multi-User

```sql
-- Step 1: Create default organization for all existing users
INSERT INTO globus_organizations (name, slug) VALUES ('Default Org', 'default');

-- Step 2: Assign all users to default org and member role
UPDATE globus_users SET 
    organization_id=1,  -- default org id
    role_id=2;          -- member role id

-- Step 3: All existing files are owner-only (no sharing)
INSERT INTO globus_file_permissions (file_id, owner_email, accessible_by_role)
SELECT id, email, NULL FROM globus_vault_files;
-- NULL = only owner can access

-- Step 4: Gradually enable team sharing
UPDATE globus_file_permissions 
SET accessible_by_role='team' 
WHERE file_id IN (SELECT id FROM globus_vault_files WHERE team_id IS NOT NULL);
```

---

## Conclusion

This POC provides:
1. **Multi-user support** with organizational hierarchy
2. **Fine-grained access control** (owner, role, team, explicit)
3. **Audit trail** for compliance
4. **Backward compatibility** with existing single-user system
5. **Scalable architecture** for enterprise use

Ready to implement in phases.

