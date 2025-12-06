const PAGE_SIZE = 50;

const EventsEls = {
	table: document.querySelector('#events-table'),
	empty: document.querySelector('#events-empty'),
	rowTemplate: document.querySelector('.pre-build-els .event-row'),
	buttons: {
		refresh: document.querySelector('#refresh-button')
	},
	filters: {
		level: document.querySelector('#level-filter')
	},
	pageTurner: {
		container: document.querySelector('.page-turner'),
		previous: document.querySelector('#previous-page'),
		next: document.querySelector('#next-page'),
		number: document.querySelector('#page-number')
	}
};

let offset = 0;
let totalPages = 0;
let currentLevelFilter = '';
let latestRecords = [];

function formatDate(value) {
	if (!value) return 'Unknown';
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return value;
	return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
}

function updatePageIndicator() {
	const pageNumber = totalPages ? Math.min(offset + 1, totalPages) : (latestRecords.length ? offset + 1 : 0);
	const suffix = totalPages ? ` of ${totalPages}` : '';
	EventsEls.pageTurner.number.innerText = pageNumber ? `Page ${pageNumber}${suffix}` : 'No pages';

	const isFirstPage = offset === 0;
	const isLastPage = totalPages ? offset + 1 >= totalPages : latestRecords.length < PAGE_SIZE;

	EventsEls.pageTurner.previous.classList.toggle('disabled', isFirstPage);
	EventsEls.pageTurner.next.classList.toggle('disabled', isLastPage);
}

function buildParams() {
	const params = {
		limit: PAGE_SIZE,
		offset
	};

	if (currentLevelFilter) {
		params.level = currentLevelFilter;
	}

	return params;
}

function renderEvents(records) {
	EventsEls.table.innerHTML = '';
	latestRecords = records;

	if (!records.length) {
		EventsEls.empty.classList.remove('hidden');
		return;
	}

	EventsEls.empty.classList.add('hidden');

	records.forEach(record => {
		const entry = EventsEls.rowTemplate.cloneNode(true);
		entry.querySelector('.time-column').innerText = formatDate(record.time);

		const levelSpan = entry.querySelector('.level-column span');
		if (levelSpan) {
			levelSpan.dataset.level = record.level;
			levelSpan.innerText = record.level.toUpperCase();
		}

		entry.querySelector('.source-column').innerText = record.source || '-';
		entry.querySelector('.message-column').innerText = record.message.split('\n')[0];

		EventsEls.table.appendChild(entry);
	});
}

function fillEvents(apiKey) {
	return fetchAPI('/system/events', apiKey, buildParams())
		.then(json => {
			totalPages = json.result.totalPages || 0;
			renderEvents(json.result.records || []);
			updatePageIndicator();
		});
}

function changePage(delta, apiKey) {
	const isMovingForward = delta > 0;
	if (!isMovingForward && offset === 0) return;
	if (isMovingForward) {
		const reachedEnd = totalPages ? offset + 1 >= totalPages : latestRecords.length < PAGE_SIZE;
		if (reachedEnd) return;
	}

	offset = Math.max(0, offset + delta);
	fillEvents(apiKey);
}

function bootstrapEvents(apiKey) {
	EventsEls.buttons.refresh.onclick = () => fillEvents(apiKey);

	EventsEls.filters.level.onchange = event => {
		currentLevelFilter = event.target.value;
		offset = 0;
		fillEvents(apiKey);
	};

	EventsEls.pageTurner.previous.onclick = () => changePage(-1, apiKey);
	EventsEls.pageTurner.next.onclick = () => changePage(1, apiKey);

	fillEvents(apiKey);
}

usingApiKey().then(apiKey => {
	bootstrapEvents(apiKey);
});
