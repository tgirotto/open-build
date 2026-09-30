/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';

const systemYaml = [
	'constraints:',
	'  envelope_mm:',
	'    x: 1000',
	'    y: 500',
	'    z: 400',
	'checks:',
	'  - name: fluid_state',
	'    fluid: Water',
	'    temperature_C: 25',
	'    pressure_bar: 1.01325',
	'    expect_phase: liquid',
	'',
].join('\n');

export async function createEngineeringProject(context: vscode.ExtensionContext): Promise<void> {
	const folder = vscode.workspace.workspaceFolders?.[0];
	if (!folder) {
		void vscode.window.showErrorMessage(vscode.l10n.t("Open a folder before creating an engineering project."));
		return;
	}

	try {
		const root = folder.uri;
		await ensureDirectory(vscode.Uri.joinPath(root, 'geometry'));
		await ensureDirectory(vscode.Uri.joinPath(root, 'catalog'));
		await ensureDirectory(vscode.Uri.joinPath(root, 'catalog', 'sources'));
		const template = await vscode.workspace.fs.readFile(vscode.Uri.joinPath(context.extensionUri, 'templates', 'part.py'));
		const catalog = await vscode.workspace.fs.readFile(vscode.Uri.joinPath(context.extensionUri, 'templates', 'components.json'));
		await writeIfMissing(vscode.Uri.joinPath(root, 'system.yaml'), systemYaml);
		await writeIfMissing(vscode.Uri.joinPath(root, 'geometry', 'part.py'), Buffer.from(template).toString('utf8'));
		await writeIfMissing(vscode.Uri.joinPath(root, 'catalog', '.gitkeep'), '');
		await writeIfMissing(vscode.Uri.joinPath(root, 'catalog', 'components.json'), Buffer.from(catalog).toString('utf8'));
		await writeIfMissing(vscode.Uri.joinPath(root, 'catalog', 'sources', '.gitkeep'), '');
		await writeIfMissing(vscode.Uri.joinPath(root, 'bom.json'), '[]\n');
		void vscode.window.showInformationMessage(vscode.l10n.t("Engineering project files are ready."));
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		void vscode.window.showErrorMessage(message);
	}
}

async function ensureDirectory(uri: vscode.Uri): Promise<void> {
	try {
		await vscode.workspace.fs.createDirectory(uri);
	} catch (error) {
		if (error instanceof vscode.FileSystemError && error.code === 'FileExists') {
			return;
		}
		throw error;
	}
}

async function writeIfMissing(uri: vscode.Uri, contents: string): Promise<void> {
	try {
		await vscode.workspace.fs.stat(uri);
		return;
	} catch (error) {
		if (!(error instanceof vscode.FileSystemError) || error.code !== 'FileNotFound') {
			throw error;
		}
	}
	await vscode.workspace.fs.writeFile(uri, Buffer.from(contents, 'utf8'));
}
