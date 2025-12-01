function togglePasswordVisibility(button) {
	const input = button.parentElement.querySelector('input');
	const isPassword = input.type === 'password';
	input.type = isPassword ? 'text' : 'password';
	button.classList.toggle('showing', isPassword);
}

function fillSettings(api_key) {
	fetchAPI('/settings', api_key)
	.then(json => {
		document.querySelector('#nzbhydra-base-url-input').value = json.result.nzbhydra_base_url || '';
		document.querySelector('#nzbhydra-api-key-input').value = json.result.nzbhydra_api_key || '';
		document.querySelector('#nzbhydra-categories-input').value = json.result.nzbhydra_categories || '';
		document.querySelector('#sabnzbd-category-input').value = json.result.sabnzbd_category || '';
		document.querySelector('#sabnzbd-priority-input').value = json.result.sabnzbd_priority || 'Normal';
	});
};

function saveSettings(api_key) {
	document.querySelector("#save-button p").innerText = 'Saving';
	const data = {
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
			console.log(e);
		});
	});
};

//
// Test NZBHydra2 connection
//
function testNZBHydra(api_key) {
	const button = document.querySelector('#test-nzbhydra-button');
	const resultDiv = document.querySelector('#test-hydra-result');

	const baseUrl = document.querySelector('#nzbhydra-base-url-input').value;
	const apiKey = document.querySelector('#nzbhydra-api-key-input').value;

	if (!baseUrl || !apiKey) {
		resultDiv.textContent = 'Please enter Base URL and API Key first';
		resultDiv.className = 'test-result error';
		resultDiv.style.display = 'block';
		setTimeout(() => resultDiv.style.display = 'none', 5000);
		return;
	}

	button.disabled = true;
	resultDiv.style.display = 'none';

	// Simple test: try to hit the API
	fetch(`${baseUrl}/api?t=search&apikey=${apiKey}&q=test&o=json`, { method: 'GET', mode: 'no-cors' })
	.then(() => {
		// Success
		button.classList.add('show-success');
		resultDiv.className = 'test-result success';
		resultDiv.textContent = 'Successfully connected to NZBHydra2';
		resultDiv.style.display = 'block';

		// Reset after 3 seconds
		setTimeout(() => {
			button.classList.remove('show-success');
			button.disabled = false;
			resultDiv.style.display = 'none';
		}, 3000);
	})
	.catch(error => {
		// Error
		button.classList.add('show-fail');
		resultDiv.className = 'test-result error';
		resultDiv.textContent = 'Connection failed - check URL and API key';
		resultDiv.style.display = 'block';

		// Reset after 3 seconds
		setTimeout(() => {
			button.classList.remove('show-fail');
			button.disabled = false;
		}, 3000);
	});
}

// code run on load
usingApiKey()
.then(api_key => {
	fillSettings(api_key);

	document.querySelector('#save-button').onclick = e => saveSettings(api_key);
	document.querySelector('#test-nzbhydra-button').onclick = e => testNZBHydra(api_key);
});
