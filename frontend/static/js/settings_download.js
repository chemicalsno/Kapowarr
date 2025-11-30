// All available download sources
const ALL_SOURCES = [
	'Mega', 'MediaFire', 'WeTransfer', 'Pixeldrain', 
	'GetComics', 'GetComics (torrent)', 'NZBHydra2'
];

function fillSettings(api_key) {
	fetchAPI('/settings', api_key)
	.then(json => {
		document.querySelector('#download-folder-input').value = json.result.download_folder;
		document.querySelector('#concurrent-direct-downloads-input').value = json.result.concurrent_direct_downloads;
		document.querySelector('#download-timeout-input').value = ((json.result.failing_download_timeout || 0) / 60) || '';
		document.querySelector('#seeding-handling-input').value = json.result.seeding_handling;
		document.querySelector('#delete-downloads-input').checked = json.result.delete_completed_downloads;
		initPrefList(json.result.service_preference);

		// NZBHydra2 / Sabnzbd settings
		document.querySelector('#nzbhydra-base-url-input').value = json.result.nzbhydra_base_url || '';
		document.querySelector('#nzbhydra-api-key-input').value = json.result.nzbhydra_api_key || '';
		document.querySelector('#nzbhydra-categories-input').value = json.result.nzbhydra_categories || '';
		document.querySelector('#sabnzbd-category-input').value = json.result.sabnzbd_category || '';
		document.querySelector('#sabnzbd-priority-input').value = json.result.sabnzbd_priority || 'Normal';
	});
};

function saveSettings(api_key) {
	document.querySelector("#save-button p").innerText = 'Saving';
	document.querySelector('#download-folder-input').classList.remove('error-input');
	const data = {
		'download_folder': document.querySelector('#download-folder-input').value,
		'concurrent_direct_downloads': parseInt(document.querySelector('#concurrent-direct-downloads-input').value),
		'failing_download_timeout': parseInt(document.querySelector('#download-timeout-input').value || 0) * 60,
		'seeding_handling': document.querySelector('#seeding-handling-input').value,
		'delete_completed_downloads': document.querySelector('#delete-downloads-input').checked,
		'service_preference': getServicePreference(),

		// NZBHydra2 / Sabnzbd settings
		'nzbhydra_base_url': document.querySelector('#nzbhydra-base-url-input').value,
		'nzbhydra_api_key': document.querySelector('#nzbhydra-api-key-input').value,
		'nzbhydra_categories': document.querySelector('#nzbhydra-categories-input').value,
		'sabnzbd_category': document.querySelector('#sabnzbd-category-input').value,
		'sabnzbd_priority': document.querySelector('#sabnzbd-priority-input').value
	};
	sendAPI('PUT', '/settings', api_key, {}, data)
	.then(response => 
		document.querySelector("#save-button p").innerText = 'Saved'
	)
	.catch(e => {
		document.querySelector("#save-button p").innerText = 'Failed';
        e.json().then(e => {
            if (
                e.error === "InvalidKeyValue"
                && e.result.key === "download_folder"
                ||
                e.error === "FolderNotFound"
            )
                document.querySelector('#download-folder-input').classList.add('error-input');

			else
                console.log(e);
        });
	});
};

//
// Empty download folder
//
function emptyFolder(api_key) {
	sendAPI('DELETE', '/activity/folder', api_key)
	.then(response => {
		document.querySelector('#empty-download-folder').innerText = 'Done';
	});
};

//
// Service preference - Sortable list
//
const prefList = document.querySelector('#pref-list');
const prefAddSelect = document.querySelector('#pref-add-select');
const prefAddBtn = document.querySelector('#pref-add-btn');

function initPrefList(prefs) {
	prefList.innerHTML = '';
	prefs.forEach(source => addPrefItem(source));
	updateAddSelect();
	setupDragAndDrop();
};

function addPrefItem(source) {
	const li = document.createElement('li');
	li.dataset.source = source;
	li.draggable = true;
	li.innerHTML = `
		<span class="drag-handle">☰</span>
		<span class="pref-name">${source}</span>
		<button type="button" class="pref-remove" title="Remove">−</button>
	`;
	
	// Remove button handler
	li.querySelector('.pref-remove').onclick = () => {
		li.remove();
		updateAddSelect();
	};
	
	prefList.appendChild(li);
};

function getServicePreference() {
	return [...prefList.querySelectorAll('li')].map(li => li.dataset.source);
};

function updateAddSelect() {
	const currentSources = new Set(getServicePreference());
	const availableSources = ALL_SOURCES.filter(s => !currentSources.has(s));
	
	// Clear and rebuild select options
	prefAddSelect.innerHTML = '<option value="" disabled selected>Add source...</option>';
	availableSources.forEach(source => {
		const option = document.createElement('option');
		option.value = source;
		option.textContent = source;
		prefAddSelect.appendChild(option);
	});
	
	// Disable add button if no sources available
	const hasAvailable = availableSources.length > 0;
	prefAddBtn.disabled = !hasAvailable;
	prefAddSelect.disabled = !hasAvailable;
};

function setupDragAndDrop() {
	let draggedItem = null;
	
	prefList.addEventListener('dragstart', e => {
		if (e.target.tagName === 'LI') {
			draggedItem = e.target;
			e.target.classList.add('dragging');
			e.dataTransfer.effectAllowed = 'move';
		}
	});
	
	prefList.addEventListener('dragend', e => {
		if (e.target.tagName === 'LI') {
			e.target.classList.remove('dragging');
			draggedItem = null;
		}
	});
	
	prefList.addEventListener('dragover', e => {
		e.preventDefault();
		e.dataTransfer.dropEffect = 'move';
		
		const afterElement = getDragAfterElement(prefList, e.clientY);
		if (draggedItem) {
			if (afterElement == null) {
				prefList.appendChild(draggedItem);
			} else {
				prefList.insertBefore(draggedItem, afterElement);
			}
		}
	});
};

function getDragAfterElement(container, y) {
	const draggableElements = [...container.querySelectorAll('li:not(.dragging)')];
	
	return draggableElements.reduce((closest, child) => {
		const box = child.getBoundingClientRect();
		const offset = y - box.top - box.height / 2;
		if (offset < 0 && offset > closest.offset) {
			return { offset: offset, element: child };
		} else {
			return closest;
		}
	}, { offset: Number.NEGATIVE_INFINITY }).element;
};

//
// Test NZBHydra2 connection
//
function testNZBHydra(api_key) {
	const button = document.querySelector('#test-nzbhydra-button');
	const icon = document.querySelector('#test-hydra-icon');
	const resultDiv = document.querySelector('#test-hydra-result');

	const baseUrl = document.querySelector('#nzbhydra-base-url-input').value;
	const apiKey = document.querySelector('#nzbhydra-api-key-input').value;

	if (!baseUrl || !apiKey) {
		resultDiv.textContent = '⚠ Please enter Base URL and API Key first';
		resultDiv.className = 'test-result error';
		resultDiv.style.display = 'block';
		setTimeout(() => resultDiv.style.display = 'none', 5000);
		return;
	}

	// Show spinner
	icon.src = icon.src.replace('refresh.svg', 'loading.svg');
	icon.classList.add('spinning');
	button.disabled = true;
	resultDiv.style.display = 'none';

	// Simple test: try to hit the API
	fetch(`${baseUrl}/api?t=search&apikey=${apiKey}&q=test&o=json`, { method: 'GET', mode: 'no-cors' })
	.then(() => {
		// Success - show checkmark
		icon.src = icon.src.replace('loading.svg', 'check.svg');
		icon.classList.remove('spinning');
		icon.classList.add('success-icon');

		resultDiv.className = 'test-result success';
		resultDiv.innerHTML = '✓ Successfully connected to NZBHydra2';
		resultDiv.style.display = 'block';

		// Reset after 5 seconds
		setTimeout(() => {
			icon.src = icon.src.replace('check.svg', 'refresh.svg');
			icon.classList.remove('success-icon');
			button.disabled = false;
			resultDiv.style.display = 'none';
		}, 5000);
	})
	.catch(error => {
		// Error - show X
		icon.src = icon.src.replace('loading.svg', 'cancel.svg');
		icon.classList.remove('spinning');
		icon.classList.add('error-icon');

		resultDiv.className = 'test-result error';
		resultDiv.textContent = '✗ Connection failed - check URL and API key';
		resultDiv.style.display = 'block';

		// Reset after 5 seconds
		setTimeout(() => {
			icon.src = icon.src.replace('cancel.svg', 'refresh.svg');
			icon.classList.remove('error-icon');
			button.disabled = false;
		}, 5000);
	});
}

// code run on load
usingApiKey()
.then(api_key => {
	fillSettings(api_key);

	document.querySelector('#save-button').onclick = e => saveSettings(api_key);
	document.querySelector('#empty-download-folder').onclick = e => emptyFolder(api_key);
	document.querySelector('#test-nzbhydra-button').onclick = e => testNZBHydra(api_key);

	// Add source button handler
	prefAddBtn.onclick = () => {
		const source = prefAddSelect.value;
		if (source) {
			addPrefItem(source);
			updateAddSelect();
			prefAddSelect.value = '';
		}
	};

	// Also add on select change for convenience
	prefAddSelect.onchange = () => {
		const source = prefAddSelect.value;
		if (source) {
			addPrefItem(source);
			updateAddSelect();
		}
	};
});
