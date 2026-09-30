/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

(function () {
	const vscode = acquireVsCodeApi();
	const empty = document.getElementById('empty');
	const body = document.getElementById('rows');

	function cell(text) {
		const item = document.createElement('td');
		item.textContent = text;
		return item;
	}

	function render(rows) {
		body.replaceChildren();
		if (!rows || rows.length === 0) {
			empty.textContent = 'No bill of materials yet.';
			return;
		}
		empty.textContent = '';
		for (const row of rows) {
			const line = document.createElement('tr');
			line.append(
				cell(row.partNumber || ''),
				cell(row.description || ''),
				cell(row.quantity === undefined || row.quantity === null ? '' : String(row.quantity)),
				cell(row.vendor || ''),
			);
			body.append(line);
		}
	}

	window.addEventListener('message', event => {
		if (event.data && event.data.type === 'bom') {
			render(event.data.rows);
		}
	});
	vscode.postMessage({ type: 'ready' });
}());
