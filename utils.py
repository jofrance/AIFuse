import csv
import pandas as pd
from openpyxl.styles import Alignment

def safe_read_csv(file_name):
    rows = []
    max_cols = 0
    with open(file_name, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(row)
            if len(row) > max_cols:
                max_cols = len(row)
    if rows and rows[0]:
        header = rows[0]
        if len(header) < max_cols:
            header += [f"col{i}" for i in range(len(header), max_cols)]
        data = rows[1:]
    else:
        header = [f"col{i}" for i in range(max_cols)]
        data = rows
    padded_data = [row + [None]*(max_cols - len(row)) for row in data]
    df = pd.DataFrame(padded_data, columns=header)
    return df

def write_csv_to_excel(csv_file, excel_file):
    try:
        df = safe_read_csv(csv_file)
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Results')
            workbook = writer.book
            sheet = writer.sheets['Results']
            for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=sheet.max_column):
                for cell in row:
                    cell.number_format = '@'
                    cell.alignment = Alignment(horizontal='left')
        print(f"Excel file written to {excel_file}")
    except Exception as e:
        print(f"Error writing Excel file: {e}")

