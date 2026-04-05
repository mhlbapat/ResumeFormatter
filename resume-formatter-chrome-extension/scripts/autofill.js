// Autofill logic for job application pages

console.log("ResumeFormatter Autofill Script injected.");

async function executeAutofill() {
    // Basic form extraction
    const inputs = document.querySelectorAll('input:not([type="hidden"]), select, textarea');
    if (inputs.length === 0) {
        console.log("No form fields found.");
        return;
    }

    let formSchema = {};
    inputs.forEach(input => {
        let name = input.name || input.id;
        if (!name) return; // Ignore fields with no name or id
        
        // Simple heuristic to get a label
        let label = "";
        if (input.labels && input.labels.length > 0) {
            label = input.labels[0].innerText;
        } else if (input.placeholder) {
            label = input.placeholder;
        }
        
        formSchema[name] = {
            id: input.id,
            type: input.type || input.tagName.toLowerCase(),
            label: label
        };
    });

    console.log("Found Form Schema:", formSchema);
    
    try {
        const response = await fetch("http://localhost:8000/autofill_form", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ form_schema: formSchema })
        });
        
        if (!response.ok) {
            console.error("Backend error getting autofill mappings", await response.text());
            return;
        }
        
        const data = await response.json();
        const mappings = data.mapped_data;
        console.log("Applying mappings:", mappings);

        // Fill fields
        for (const [key, val] of Object.entries(mappings)) {
            if (!val) continue;

            const targetInput = document.querySelector(`[name="${key}"], [id="${key}"]`);
            if (targetInput) {
                targetInput.value = val;
                // Dispatch events to trigger JS frameworks (React/Vue)
                targetInput.dispatchEvent(new Event('input', { bubbles: true }));
                targetInput.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }
        
        alert("ResumeFormatter Autofill Complete! Please review before hitting Submit.");
    } catch (e) {
        console.error("Error during auto-fill", e);
    }
}

// Check if we are auto-triggered or run manually via message
// For now, let's just trigger immediately when injected
setTimeout(executeAutofill, 2000);
