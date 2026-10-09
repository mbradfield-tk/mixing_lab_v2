import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, unwrap } from "../api/client";
import { PropertyTable } from "../components/PropertyTable";
import { Card, ErrorNote, PageTitle } from "../components/ui";
import { formatConverted, formatG } from "../format";

const GAS_FLOW = "Gas flow rate";

export function UnitConverter() {
  const table = useQuery({
    queryKey: ["units"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/units")) as {
        properties: Record<string, string[]>;
        gas_reference: Record<string, string>[];
      },
    staleTime: Infinity,
  });

  const [property, setProperty] = useState("Pressure");
  const [fromUnit, setFromUnit] = useState("");
  const [value, setValue] = useState("1");
  const [gasT, setGasT] = useState("25");
  const [gasP, setGasP] = useState("1");

  const units = table.data?.properties[property] ?? [];
  useEffect(() => {
    if (units.length && !units.includes(fromUnit)) setFromUnit(units[0]);
  }, [units, fromUnit]);

  const numbers = [Number(value), Number(gasT), Number(gasP)];
  const ready = fromUnit !== "" && units.includes(fromUnit) && numbers.every(Number.isFinite);
  const result = useQuery({
    queryKey: ["convert", property, fromUnit, ...numbers],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/units/convert", {
          body: {
            property,
            from_unit: fromUnit,
            value: numbers[0],
            gas_T_C: numbers[1],
            gas_P_atm: numbers[2],
          },
        }),
      ),
    enabled: ready,
    placeholderData: keepPreviousData,
  });

  const rows = Object.entries(result.data?.converted ?? {}).filter(([unit]) => unit !== fromUnit);

  return (
    <>
      <PageTitle pageKey="Unit_Converter">Unit Converter</PageTitle>
      <p>General unit conversions for physical properties relevant to mixing and reactor engineering.</p>

      <Card title="Convert">
        {table.isError && <ErrorNote error={table.error} />}
        <div className="prop-narrow">
          <PropertyTable
            groups={[
              {
                title: "Input",
                rows: [
                  { label: "Physical property", value: property, options: Object.keys(table.data?.properties ?? {}), onChange: setProperty },
                  { label: "From unit", value: fromUnit, options: units, onChange: setFromUnit },
                  { label: "Value", unit: fromUnit, value, onChange: setValue },
                ],
              },
              ...(property === GAS_FLOW
                ? [
                    {
                      title: "Actual gas conditions",
                      rows: [
                        { label: "Gas temperature", unit: "°C", value: gasT, onChange: setGasT },
                        { label: "Gas pressure", unit: "atm", value: gasP, onChange: setGasP },
                      ],
                    },
                  ]
                : []),
            ]}
          />
        </div>

        {property === GAS_FLOW && (
          <>
            <p className="muted">Gas flow conversions use the ideal-gas law at the actual temperature and pressure above.</p>
            <details>
              <summary>Reference conditions</summary>
              <table>
                <thead>
                  <tr>
                    <th>Basis</th>
                    <th>T_ref</th>
                    <th>P_ref</th>
                    <th>Standard</th>
                  </tr>
                </thead>
                <tbody>
                  {table.data?.gas_reference.map((r) => (
                    <tr key={r.Basis}>
                      <td>{r.Basis}</td>
                      <td>{r.T_ref}</td>
                      <td>{r.P_ref}</td>
                      <td>{r.Standard}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </>
        )}
      </Card>

      <Card title="Results">
        <h3>
          {Number.isFinite(numbers[0]) ? formatG(numbers[0]) : value} {fromUnit}
        </h3>
        {result.isError && <ErrorNote error={result.error} />}
        <table className="results">
          <thead>
            <tr>
              <th>Unit</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([unit, v]) => (
              <tr key={unit}>
                <td>{unit}</td>
                <td className="num">{formatConverted(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
