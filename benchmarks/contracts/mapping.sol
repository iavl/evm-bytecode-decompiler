pragma solidity ^0.8.0;
contract MappingFixture { mapping(address => uint256) internal values; function set(uint256 value) external { values[msg.sender] = value; } function get(address key) external view returns (uint256) { return values[key]; } }
